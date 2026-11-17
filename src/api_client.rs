//! Client for the Deadlock Assets API (assets.deadlock-api.com).
//!
//! Fetches hero and item data and caches it locally as JSON files. Data is only
//! refreshed when explicitly requested, or on first run when no cache exists.

use std::fs;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::{Duration, SystemTime};

use serde::Serialize;
use serde_json::{Map, Value};

use crate::models::str_of;

pub const BASE_URL: &str = "https://assets.deadlock-api.com";
const TIMEOUT: Duration = Duration::from_secs(30);

/// Root of the `data/` directory.
///
/// Resolution order: `DEADLOCKSIM_DATA_DIR`, `./data`, `data` next to the
/// executable, then the source checkout this binary was built from.
pub fn data_dir() -> PathBuf {
    static DIR: OnceLock<PathBuf> = OnceLock::new();
    DIR.get_or_init(|| {
        if let Ok(d) = std::env::var("DEADLOCKSIM_DATA_DIR") {
            return PathBuf::from(d);
        }
        let mut candidates = vec![PathBuf::from("data")];
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                candidates.push(dir.join("data"));
            }
        }
        candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data"));
        candidates.iter().find(|c| c.join("api_cache").is_dir()).cloned().unwrap_or_else(|| PathBuf::from("data"))
    })
    .clone()
}

fn cache_path(name: &str) -> PathBuf {
    data_dir().join("api_cache").join(format!("{name}.json"))
}

fn base_url() -> String {
    std::env::var("DEADLOCKSIM_API_URL").unwrap_or_else(|_| BASE_URL.to_string())
}

/// GET a URL and return the body as text.
pub fn http_get(url: &str) -> Result<String, String> {
    let config = ureq::Agent::config_builder()
        .timeout_global(Some(TIMEOUT))
        .tls_config(
            ureq::tls::TlsConfig::builder().root_certs(ureq::tls::RootCerts::PlatformVerifier).build(),
        )
        .build();
    let agent: ureq::Agent = config.into();
    let mut resp = agent
        .get(url)
        .header("User-Agent", "deadlock-sim")
        .call()
        .map_err(|e| format!("GET {url} failed: {e}"))?;
    resp.body_mut()
        .with_config()
        .limit(256 * 1024 * 1024)
        .read_to_string()
        .map_err(|e| format!("reading {url} failed: {e}"))
}

fn get_json(path: &str, language: &str) -> Result<Value, String> {
    let url = format!("{}{path}?language={language}", base_url());
    let body = http_get(&url)?;
    serde_json::from_str(&body).map_err(|e| format!("{url} returned invalid JSON: {e}"))
}

/// Save API response data to the local cache (atomically).
pub fn save_cache(name: &str, data: &Value) -> Result<(), String> {
    let path = cache_path(name);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
    }
    let tmp = path.with_extension("json.tmp");
    let body = serde_json::to_string_pretty(data).map_err(|e| e.to_string())?;
    fs::write(&tmp, body).map_err(|e| format!("cannot write {}: {e}", tmp.display()))?;
    fs::rename(&tmp, &path).map_err(|e| format!("cannot replace {}: {e}", path.display()))
}

/// Load cached data. Returns `None` if the cache file is missing or unreadable.
pub fn load_cache(name: &str) -> Option<Value> {
    let body = fs::read_to_string(cache_path(name)).ok()?;
    serde_json::from_str(&body).ok()
}

/// Whether cached hero and item data exists.
pub fn is_cache_available() -> bool {
    cache_path("heroes").exists() && cache_path("items").exists()
}

/// Seconds since the cache was last written, if it exists.
pub fn cache_age_seconds() -> Option<u64> {
    let modified = fs::metadata(cache_path("items")).ok()?.modified().ok()?;
    SystemTime::now().duration_since(modified).ok().map(|d| d.as_secs())
}

/// Counts from a data refresh.
#[derive(Debug, Clone, Default, Serialize)]
pub struct RefreshSummary {
    pub heroes: usize,
    pub items: usize,
    pub abilities: usize,
    pub weapons: usize,
    pub upgrades: usize,
    /// Heroes whose per-hero item list could not be fetched.
    pub failed_heroes: Vec<String>,
}

/// Fetch all data from the API and save it to the local cache.
///
/// Nothing is written until the hero and item lists have both been fetched, so
/// a failed refresh leaves the existing cache intact.
pub fn refresh_all_data(language: &str) -> Result<RefreshSummary, String> {
    let heroes = get_json("/v2/heroes", language)?;
    let items = get_json("/v2/items", language)?;
    let hero_list = heroes.as_array().ok_or("heroes endpoint did not return a list")?;
    let item_list = items.as_array().ok_or("items endpoint did not return a list")?;

    let of_type = |t: &str| -> Value {
        Value::Array(item_list.iter().filter(|i| str_of(i, "type") == t).cloned().collect())
    };
    let (abilities, weapons, upgrades) = (of_type("ability"), of_type("weapon"), of_type("upgrade"));

    // Items per hero, for ability mapping.
    let mut hero_items = Map::new();
    let mut failed = Vec::new();
    for hero in hero_list {
        let Some(id) = hero.get("id").filter(|v| !v.is_null()) else { continue };
        let id = crate::models::text(id);
        match get_json(&format!("/v2/items/by-hero-id/{id}"), language) {
            Ok(v) => {
                hero_items.insert(id, v);
            }
            Err(e) => {
                eprintln!("warning: failed to fetch items for hero {id}: {e}");
                failed.push(str_of(hero, "name").to_string());
            }
        }
    }

    let summary = RefreshSummary {
        heroes: hero_list.len(),
        items: item_list.len(),
        abilities: abilities.as_array().map_or(0, Vec::len),
        weapons: weapons.as_array().map_or(0, Vec::len),
        upgrades: upgrades.as_array().map_or(0, Vec::len),
        failed_heroes: failed,
    };
    save_cache("heroes", &heroes)?;
    save_cache("items", &items)?;
    save_cache("abilities", &abilities)?;
    save_cache("weapons", &weapons)?;
    save_cache("upgrades", &upgrades)?;
    save_cache("hero_items", &Value::Object(hero_items))?;
    Ok(summary)
}

/// Fetch and cache API data if not already cached.
pub fn ensure_data_available() -> Result<(), String> {
    if is_cache_available() {
        return Ok(());
    }
    eprintln!("No local cache found — fetching data from the Deadlock Assets API...");
    refresh_all_data("english").map(|_| ())
}
