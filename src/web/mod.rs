//! Web UI: an HTTP API over the service layer plus an embedded single-page app.

use std::net::SocketAddr;
use std::sync::{Arc, Mutex, RwLock};
use std::time::Instant;

use axum::extract::{Path, Query, State};
use axum::http::{header, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::json;

use crate::api_client;
use crate::data::GameData;
use crate::service::{self, ServiceResult};

const INDEX_HTML: &str = include_str!("static/index.html");
const APP_JS: &str = include_str!("static/app.js");
const STYLE_CSS: &str = include_str!("static/style.css");

/// Minimum seconds between data refreshes.
const REFRESH_COOLDOWN_SECS: u64 = 60;
const MAX_FEEDBACK_CHARS: usize = 2000;

pub struct AppState {
    data: RwLock<Arc<GameData>>,
    last_refresh: Mutex<Option<Instant>>,
}

type Shared = Arc<AppState>;

impl AppState {
    fn data(&self) -> Arc<GameData> {
        self.data.read().expect("data lock").clone()
    }
}

fn respond(result: ServiceResult) -> Response {
    match result {
        Ok(v) => Json(v).into_response(),
        Err(e) => (StatusCode::BAD_REQUEST, Json(json!({"error": e}))).into_response(),
    }
}

/// Run a service call off the async runtime (simulations can take a while).
async fn blocking<F>(state: Shared, f: F) -> Response
where
    F: FnOnce(&GameData) -> ServiceResult + Send + 'static,
{
    let data = state.data();
    match tokio::task::spawn_blocking(move || f(&data)).await {
        Ok(result) => respond(result),
        Err(e) => {
            eprintln!("error: request handler panicked: {e}");
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": "Internal error while computing the result."})))
                .into_response()
        }
    }
}

/// POST handler for a service function taking a JSON request body.
fn api<R, F>(f: F) -> axum::routing::MethodRouter<Shared>
where
    R: DeserializeOwned + Send + 'static,
    F: Fn(&GameData, &R) -> ServiceResult + Clone + Send + Sync + 'static,
{
    post(move |State(state): State<Shared>, Json(req): Json<R>| {
        let f = f.clone();
        async move { blocking(state, move |d| f(d, &req)).await }
    })
}

fn asset(content_type: &'static str, body: &'static str) -> Response {
    (
        [
            (header::CONTENT_TYPE, HeaderValue::from_static(content_type)),
            (header::CACHE_CONTROL, HeaderValue::from_static("no-cache")),
        ],
        body,
    )
        .into_response()
}

/// Serve a bundled image from `data/images/<dir>/<file>`.
async fn image(dir: &'static str, file: String) -> Response {
    let safe = !file.is_empty()
        && !file.starts_with('.')
        && file.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'));
    if !safe {
        return StatusCode::NOT_FOUND.into_response();
    }
    let path = api_client::data_dir().join("images").join(dir).join(&file);
    match tokio::task::spawn_blocking(move || std::fs::read(path)).await {
        Ok(Ok(bytes)) => {
            let content_type = if file.ends_with(".webp") { "image/webp" } else { "image/png" };
            (
                [
                    (header::CONTENT_TYPE, HeaderValue::from_static(content_type)),
                    (header::CACHE_CONTROL, HeaderValue::from_static("public, max-age=86400")),
                ],
                bytes,
            )
                .into_response()
        }
        _ => StatusCode::NOT_FOUND.into_response(),
    }
}

#[derive(Deserialize)]
struct AddItemReq {
    #[serde(default)]
    items: Vec<String>,
    item: String,
}

#[derive(Deserialize)]
struct RankQuery {
    #[serde(default)]
    stat: Option<String>,
    #[serde(default)]
    boons: i64,
}

#[derive(Deserialize)]
struct HeroPairQuery {
    a: String,
    b: String,
    #[serde(default)]
    boons: i64,
}

#[derive(Deserialize)]
struct CodeQuery {
    code: String,
}

#[derive(Deserialize)]
struct Feedback {
    #[serde(default)]
    category: String,
    #[serde(default)]
    text: String,
}

async fn refresh(State(state): State<Shared>) -> Response {
    {
        let mut last = state.last_refresh.lock().expect("refresh lock");
        if let Some(t) = *last {
            let waited = t.elapsed().as_secs();
            if waited < REFRESH_COOLDOWN_SECS {
                let msg =
                    format!("Data was refreshed {waited}s ago. Try again in {}s.", REFRESH_COOLDOWN_SECS - waited);
                return (StatusCode::TOO_MANY_REQUESTS, Json(json!({"error": msg}))).into_response();
            }
        }
        *last = Some(Instant::now());
    }
    let outcome = tokio::task::spawn_blocking(|| {
        let summary = api_client::refresh_all_data("english")?;
        Ok::<_, String>((summary, GameData::load()?))
    })
    .await;
    match outcome {
        Ok(Ok((summary, data))) => {
            *state.data.write().expect("data lock") = Arc::new(data);
            Json(json!({"summary": summary})).into_response()
        }
        Ok(Err(e)) => {
            eprintln!("warning: data refresh failed: {e}");
            // A failed attempt should not block an immediate retry.
            *state.last_refresh.lock().expect("refresh lock") = None;
            (StatusCode::BAD_GATEWAY, Json(json!({"error": format!("Refresh failed: {e}")}))).into_response()
        }
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"error": e.to_string()}))).into_response(),
    }
}

async fn feedback(Json(fb): Json<Feedback>) -> Response {
    let clean = |s: &str, max: usize| -> String {
        s.chars().filter(|c| !c.is_control() || *c == ' ').take(max).collect::<String>().trim().to_string()
    };
    let body = clean(&fb.text.replace(['\n', '\r', '\t'], " "), MAX_FEEDBACK_CHARS);
    if body.is_empty() {
        return (StatusCode::BAD_REQUEST, Json(json!({"error": "Please enter a description."}))).into_response();
    }
    // Tagged for easy searching in hosted log streams.
    println!("[USER_FEEDBACK] category={} | {body}", clean(&fb.category, 32));
    Json(json!({"ok": true})).into_response()
}

pub fn router(data: GameData) -> Router {
    let state: Shared = Arc::new(AppState { data: RwLock::new(Arc::new(data)), last_refresh: Mutex::new(None) });
    Router::new()
        .route("/", get(|| async { asset("text/html; charset=utf-8", INDEX_HTML) }))
        .route("/app.js", get(|| async { asset("text/javascript; charset=utf-8", APP_JS) }))
        .route("/style.css", get(|| async { asset("text/css; charset=utf-8", STYLE_CSS) }))
        .route("/healthz", get(|| async { "ok" }))
        .route("/static/items/{file}", get(|Path(file): Path<String>| image("items", file)))
        .route("/static/ui/{file}", get(|Path(file): Path<String>| image("ui", file)))
        .route(
            "/api/catalog",
            get(|State(s): State<Shared>| async move { blocking(s, |d| Ok(service::catalog(d))).await }),
        )
        .route("/api/build/evaluate", api(service::evaluate))
        .route("/api/build/add", api(|d: &GameData, r: &AddItemReq| service::add_item(d, &r.items, &r.item)))
        .route("/api/build/scores", api(service::score_items))
        .route("/api/build/matchups", api(service::matchups))
        .route("/api/build/curves", api(service::curves))
        .route("/api/build/optimize", api(service::optimize))
        .route("/api/build/recommend", api(service::recommend))
        .route("/api/build/compare", api(service::compare_builds))
        .route("/api/simulate", api(service::simulate))
        .route("/api/montecarlo", api(service::monte_carlo))
        .route(
            "/api/heroes/rankings",
            get(|State(s): State<Shared>, Query(q): Query<RankQuery>| async move {
                blocking(s, move |d| service::rankings(d, q.stat.as_deref().unwrap_or("dps"), q.boons, usize::MAX))
                    .await
            }),
        )
        .route(
            "/api/heroes/compare",
            get(|State(s): State<Shared>, Query(q): Query<HeroPairQuery>| async move {
                blocking(s, move |d| service::compare_heroes(d, &q.a, &q.b, q.boons)).await
            }),
        )
        .route(
            "/api/share/decode",
            get(|State(s): State<Shared>, Query(q): Query<CodeQuery>| async move {
                blocking(s, move |d| service::decode_share(d, &q.code)).await
            }),
        )
        .route("/api/patches", get(|| async { Json(service::list_patches()) }))
        .route(
            "/api/patches/latest",
            post(|State(s): State<Shared>| async move { blocking(s, service::fetch_latest_patch).await }),
        )
        .route(
            "/api/patches/{date}",
            get(|State(s): State<Shared>, Path(date): Path<String>| async move {
                blocking(s, move |d| service::patch_report(d, &date)).await
            }),
        )
        .route("/api/refresh", post(refresh))
        .route("/api/feedback", post(feedback))
        .with_state(state)
}

/// Serve the web UI until interrupted.
pub async fn serve(data: GameData, host: &str, port: u16) -> Result<(), String> {
    let addr: SocketAddr =
        format!("{host}:{port}").parse().map_err(|e| format!("invalid address {host}:{port}: {e}"))?;
    let listener = tokio::net::TcpListener::bind(addr).await.map_err(|e| format!("cannot listen on {addr}: {e}"))?;
    let shown = if host == "0.0.0.0" { format!("localhost:{port}") } else { addr.to_string() };
    println!("Deadlock Combat Simulator listening on http://{shown}");
    axum::serve(listener, router(data))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .map_err(|e| e.to_string())
}
