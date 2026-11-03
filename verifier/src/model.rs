//! JSON types mirroring the Python pipeline's Pydantic models
//! (`src/qa_agent/graph/state.py`), field-for-field, so a `/verify` request
//! round-trips without a translation layer on either side.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCase {
    pub id: String,
    pub title: String,
    pub priority: String,
    pub steps: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StepResult {
    pub description: String,
    pub status: String,
    #[serde(default)]
    pub tool_calls: Vec<serde_json::Value>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub screenshot_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCaseResult {
    pub test_case_id: String,
    pub title: String,
    pub priority: String,
    #[serde(default)]
    pub steps: Vec<StepResult>,
    #[serde(default)]
    pub verdict: Option<String>,
    #[serde(default)]
    pub reasoning: Option<String>,
    #[serde(default)]
    pub suspected_bug: bool,
    pub started_at: String,
    #[serde(default)]
    pub finished_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerifyRequest {
    pub run_id: String,
    pub test_plan: Vec<TestCase>,
    pub test_results: Vec<TestCaseResult>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Error,
    Warning,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Violation {
    pub law: String,
    pub scope: String,
    pub severity: Severity,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub corrected_verdict: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerificationReport {
    pub consistent: bool,
    pub violations: Vec<Violation>,
    pub checked_at: String,
}
