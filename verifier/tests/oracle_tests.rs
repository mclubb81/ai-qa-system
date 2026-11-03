use qa_verifier::model::{StepResult, TestCaseResult, VerifyRequest};
use qa_verifier::oracle::check_consistency;

fn step(status: &str) -> StepResult {
    StepResult {
        description: "step".into(),
        status: status.into(),
        tool_calls: vec![],
        error: None,
        screenshot_path: None,
    }
}

fn result(verdict: Option<&str>, steps: Vec<StepResult>) -> TestCaseResult {
    TestCaseResult {
        test_case_id: "tc-1".into(),
        title: "Test".into(),
        priority: "high".into(),
        steps,
        verdict: verdict.map(String::from),
        reasoning: None,
        suspected_bug: false,
        started_at: "2026-01-01T00:00:00Z".into(),
        finished_at: None,
    }
}

#[test]
fn all_pass_steps_with_pass_verdict_is_consistent() {
    let r = result(Some("pass"), vec![step("pass"), step("pass")]);
    assert!(check_consistency(&r).is_none());
}

#[test]
fn failing_step_with_pass_verdict_is_a_violation() {
    let r = result(Some("pass"), vec![step("pass"), step("fail")]);
    let v = check_consistency(&r).expect("expected a violation");
    assert_eq!(v.law, "functor_consistency");
    assert_eq!(v.scope, "tc-1");
    assert_eq!(v.corrected_verdict, Some("fail".to_string()));
}

#[test]
fn failing_step_with_fail_verdict_is_consistent() {
    let r = result(Some("fail"), vec![step("pass"), step("fail")]);
    assert!(check_consistency(&r).is_none());
}

#[test]
fn flaky_verdict_is_never_flagged() {
    let r = result(Some("flaky"), vec![step("fail")]);
    assert!(check_consistency(&r).is_none());
}

#[test]
fn unanalyzed_result_is_skipped() {
    let r = result(None, vec![step("fail")]);
    assert!(check_consistency(&r).is_none());
}

#[test]
fn no_step_evidence_is_skipped_by_the_oracle() {
    let r = result(Some("pass"), vec![]);
    assert!(check_consistency(&r).is_none());
}

#[test]
fn fixture_request_round_trips_and_detects_the_seeded_inconsistency() {
    let data = std::fs::read_to_string("tests/fixtures/sample_verify_request.json")
        .expect("fixture file should exist");
    let req: VerifyRequest = serde_json::from_str(&data).expect("fixture should deserialize");

    assert_eq!(req.run_id, "sample-run-001");
    assert_eq!(req.test_plan.len(), 2);

    let report = qa_verifier::report::build_report(&req);
    assert!(!report.consistent);
    assert_eq!(report.violations.len(), 1);
    assert_eq!(report.violations[0].scope, "tc-2");
    assert_eq!(report.violations[0].corrected_verdict, Some("fail".to_string()));
}
