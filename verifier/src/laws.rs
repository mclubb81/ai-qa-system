//! Composition-law checks across the pipeline DAG: does the direct
//! Planner -> Analyzer contract hold for every analyzed test case? A test
//! case that's locally plausible at each hop but incoherent end-to-end
//! (e.g. analyzed without ever being planned, or analyzed without any
//! recorded step evidence) is exactly what this catches.

use std::collections::HashSet;

use crate::model::{Severity, TestCase, TestCaseResult, Violation};

pub fn check_pipeline_composition(
    test_plan: &[TestCase],
    test_results: &[TestCaseResult],
) -> Vec<Violation> {
    let mut violations = Vec::new();
    let planned_ids: HashSet<&str> = test_plan.iter().map(|tc| tc.id.as_str()).collect();

    for result in test_results {
        if result.verdict.is_none() {
            continue; // not yet analyzed -- nothing to check yet
        }

        if !planned_ids.contains(result.test_case_id.as_str()) {
            violations.push(Violation {
                law: "composition_contract".to_string(),
                scope: "pipeline".to_string(),
                severity: Severity::Error,
                message: format!(
                    "Test case '{}' was analyzed but does not appear in the test plan",
                    result.test_case_id
                ),
                corrected_verdict: None,
            });
        }

        if result.steps.is_empty() {
            violations.push(Violation {
                law: "composition_contract".to_string(),
                scope: "pipeline".to_string(),
                severity: Severity::Error,
                message: format!(
                    "Test case '{}' has a verdict but no recorded step evidence",
                    result.test_case_id
                ),
                corrected_verdict: None,
            });
        }
    }

    violations
}
