use std::net::SocketAddr;

use axum::{
    routing::{get, post},
    Json, Router,
};
use qa_verifier::model::{VerificationReport, VerifyRequest};
use qa_verifier::report;

async fn healthz() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok"}))
}

async fn verify(Json(req): Json<VerifyRequest>) -> Json<VerificationReport> {
    Json(report::build_report(&req))
}

#[tokio::main]
async fn main() {
    let app = Router::new()
        .route("/healthz", get(healthz))
        .route("/verify", post(verify));

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8787);
    let addr = SocketAddr::from(([127, 0, 0, 1], port));

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .expect("failed to bind verifier listener");
    println!("qa-verifier listening on {addr}");
    axum::serve(listener, app)
        .await
        .expect("verifier server crashed");
}
