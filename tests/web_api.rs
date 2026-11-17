//! HTTP API tests: drive the axum router in-process.

use axum::body::Body;
use axum::http::{Request, StatusCode};
use axum::Router;
use deadlock_sim::data::GameData;
use deadlock_sim::web;
use http_body_util::BodyExt;
use serde_json::{json, Value};
use tower::ServiceExt;

fn app() -> Router {
    web::router(GameData::load().expect("api cache"))
}

async fn send(app: &Router, req: Request<Body>) -> (StatusCode, Vec<u8>) {
    let resp = app.clone().oneshot(req).await.unwrap();
    let status = resp.status();
    (status, resp.into_body().collect().await.unwrap().to_bytes().to_vec())
}

async fn get(app: &Router, uri: &str) -> (StatusCode, Value) {
    let (s, body) = send(app, Request::get(uri).body(Body::empty()).unwrap()).await;
    (s, serde_json::from_slice(&body).unwrap_or(Value::Null))
}

async fn post(app: &Router, uri: &str, body: Value) -> (StatusCode, Value) {
    let req = Request::post(uri).header("content-type", "application/json").body(Body::from(body.to_string())).unwrap();
    let (s, body) = send(app, req).await;
    (s, serde_json::from_slice(&body).unwrap_or(Value::Null))
}

fn build() -> Value {
    json!({"hero": "Haze", "items": ["Headshot Booster", "Extra Health"], "extra_souls": 500, "ability_upgrades": {"0": 1}})
}

#[tokio::test]
async fn serves_the_page_assets_and_health_check() {
    let app = app();
    for (uri, kind) in [("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")] {
        let resp = app.clone().oneshot(Request::get(uri).body(Body::empty()).unwrap()).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK, "{uri}");
        assert!(resp.headers()["content-type"].to_str().unwrap().starts_with(kind), "{uri}");
    }
    let (s, body) = send(&app, Request::get("/healthz").body(Body::empty()).unwrap()).await;
    assert_eq!((s, body.as_slice()), (StatusCode::OK, b"ok".as_slice()));
}

#[tokio::test]
async fn static_images_are_served_and_paths_are_confined() {
    let app = app();
    let resp =
        app.clone().oneshot(Request::get("/static/ui/all_stats.png").body(Body::empty()).unwrap()).await.unwrap();
    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(resp.headers()["content-type"], "image/png");
    for uri in [
        "/static/items/..%2F..%2FCargo.toml",
        "/static/items/.hidden",
        "/static/items/missing.png",
        "/static/ui/..%5Csecret",
    ] {
        let (s, _) = send(&app, Request::get(uri).body(Body::empty()).unwrap()).await;
        assert_eq!(s, StatusCode::NOT_FOUND, "{uri}");
    }
}

#[tokio::test]
async fn catalog_lists_heroes_items_and_defaults() {
    let (s, v) = get(&app(), "/api/catalog").await;
    assert_eq!(s, StatusCode::OK);
    assert!(v["heroes"].as_array().unwrap().len() > 30);
    assert!(v["items"].as_array().unwrap().len() > 100);
    assert_eq!(v["max_items"], 12);
    assert!(v["default_settings"]["accuracy"].is_number());
}

#[tokio::test]
async fn build_endpoints_round_trip() {
    let app = app();
    let (s, v) = post(&app, "/api/build/evaluate", json!({"build": build()})).await;
    assert_eq!(s, StatusCode::OK);
    let d = GameData::load().unwrap();
    let cost = d.items["Headshot Booster"].cost + d.items["Extra Health"].cost;
    assert_eq!(v["souls"]["items"], cost);
    assert_eq!(v["souls"]["total"], cost + 500);
    let code = v["share_code"].as_str().unwrap().to_string();

    let (s, d) = get(&app, &format!("/api/share/decode?code={code}")).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(d["build"]["items"], json!(["Headshot Booster", "Extra Health"]));
    assert_eq!(d["build"]["extra_souls"], 500);
    assert_eq!(d["build"]["ability_upgrades"]["0"], 1);

    let (s, add) = post(&app, "/api/build/add", json!({"items": ["Headshot Booster"], "item": "headhunter"})).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!((add["status"].as_str(), &add["items"]), (Some("upgraded"), &json!(["Headhunter"])));
    let (_, dup) = post(&app, "/api/build/add", json!({"items": ["Headhunter"], "item": "Headhunter"})).await;
    assert_eq!(dup["status"], "duplicate");
}

#[tokio::test]
async fn analysis_endpoints_answer() {
    let app = app();
    let b = build();
    let cases = [
        ("/api/build/scores", json!({"build": b, "mode": "fast"}), "scores"),
        ("/api/build/scores", json!({"build": b, "mode": "gun", "candidates": ["Extended Magazine"]}), "scores"),
        ("/api/build/matchups", json!({"build": b}), "matchups"),
        ("/api/build/curves", json!({"build": b}), "power"),
        ("/api/build/recommend", json!({"build": b, "goal": "gun", "limit": 3}), "recommendations"),
        ("/api/build/optimize", json!({"build": b, "goal": "tank", "budget": 6000}), "result"),
        ("/api/build/compare", json!({"a": b, "b": {"hero": "Abrams"}}), "rows"),
        ("/api/simulate", json!({"build": b, "defender": {"hero": "Abrams"}}), "sides"),
        ("/api/montecarlo", json!({"build": b, "defender": {"hero": "Abrams"}, "trials": 200}), "distribution"),
    ];
    for (uri, body, key) in cases {
        let (s, v) = post(&app, uri, body).await;
        assert_eq!(s, StatusCode::OK, "{uri}: {v}");
        assert!(!v[key].is_null(), "{uri} is missing {key}");
    }
    let (_, opt) = post(&app, "/api/build/optimize", json!({"build": b, "goal": "tank", "budget": 6000})).await;
    assert!(opt["result"]["total_cost"].as_i64().unwrap() <= 6000);
    assert!(opt["result"]["items"].as_array().unwrap().contains(&json!("Headshot Booster")), "locked item dropped");
}

#[tokio::test]
async fn hero_and_patch_endpoints_answer() {
    let app = app();
    let (s, v) = get(&app, "/api/heroes/rankings?stat=hp&boons=10").await;
    assert_eq!(s, StatusCode::OK);
    let values: Vec<f64> = v["rankings"].as_array().unwrap().iter().map(|r| r["value"].as_f64().unwrap()).collect();
    assert!(values.windows(2).all(|w| w[0] >= w[1]));
    let (s, v) = get(&app, "/api/heroes/compare?a=haze&b=abrams&boons=5").await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(v["at"]["hero_a_name"], "Haze");

    let (s, v) = get(&app, "/api/patches").await;
    assert_eq!(s, StatusCode::OK);
    let date = v["patches"][0].as_str().unwrap().to_string();
    let (s, v) = get(&app, &format!("/api/patches/{date}")).await;
    assert_eq!(s, StatusCode::OK);
    assert_eq!(v["total"].as_u64().unwrap() as usize, v["entries"].as_array().unwrap().len());
    let (s, _) = get(&app, "/api/patches/..%2F..%2FCargo").await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
}

#[tokio::test]
async fn bad_requests_get_clear_errors() {
    let app = app();
    let (s, v) = post(&app, "/api/build/evaluate", json!({"build": {"hero": "Nobody"}})).await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("Nobody"));
    let (s, v) =
        post(&app, "/api/build/evaluate", json!({"build": {"hero": "Haze", "items": ["Hedshot Booster"]}})).await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    assert!(v["error"].as_str().unwrap().contains("Did you mean"), "{v}");
    let (s, _) = post(&app, "/api/build/scores", json!({"build": build(), "mode": "bogus"})).await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    let (s, _) = get(&app, "/api/heroes/rankings?stat=bogus").await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    let (s, _) = get(&app, "/api/share/decode?code=garbage").await;
    assert_eq!(s, StatusCode::BAD_REQUEST);

    let req =
        Request::post("/api/simulate").header("content-type", "application/json").body(Body::from("not json")).unwrap();
    let (s, _) = send(&app, req).await;
    assert!(s.is_client_error());
}

#[tokio::test]
async fn out_of_range_settings_are_clamped_not_rejected() {
    let body = json!({"build": build(), "settings": {"accuracy": 9, "headshot_rate": -2, "duration": 100000}});
    let (s, v) = post(&app(), "/api/build/evaluate", body).await;
    assert_eq!(s, StatusCode::OK, "{v}");
    let (s, v) = post(
        &app(),
        "/api/simulate",
        json!({"build": build(), "defender": {"hero": "Abrams"}, "settings": {"duration": 100000}}),
    )
    .await;
    assert_eq!(s, StatusCode::OK);
    assert!(v["configured_duration"].as_f64().unwrap() <= 120.0);
}

#[tokio::test]
async fn feedback_requires_text() {
    let app = app();
    let (s, _) = post(&app, "/api/feedback", json!({"category": "Bug", "text": "   "})).await;
    assert_eq!(s, StatusCode::BAD_REQUEST);
    let (s, v) = post(&app, "/api/feedback", json!({"category": "Bug", "text": "works"})).await;
    assert_eq!((s, &v["ok"]), (StatusCode::OK, &json!(true)));
}
