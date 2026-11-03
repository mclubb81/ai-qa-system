//! The independent correctness oracle: a functor `F` mapping raw evidence
//! (`StepResult`s) to the category of verdicts, used to check that the
//! Analyzer's self-reported verdict agrees with what the evidence implies.

use crate::model::{Severity, StepResult, TestCaseResult, Violation};

/// `F`: evidence -> expected verdict. Any failing step implies the overall
/// case failed; otherwise it passed.
pub fn expected_verdict(steps: &[StepResult]) -> &'static str {
    if steps.iter().any(|s| s.status == "fail") {
        "fail"
    } else {
        "pass"
    }
}

/// Compares `result.verdict` against `F(result.steps)`. Returns `None` when
/// there's nothing to compare yet (unanalyzed), when the verdict is
/// "flaky" (outside the binary pass/fail image of `F`), or when there's no
/// step evidence at all (an evidence gap, which `laws.rs` already flags).
pub fn check_consistency(result: &TestCaseResult) -> Option<Violation> {
    let verdict = result.verdict.as_deref()?;
    if verdict == "flaky" || result.steps.is_empty() {
        return None;
    }

    let expected = expected_verdict(&result.steps);
    if verdict == expected {
        return None;
    }

    Some(Violation {
        law: "functor_consistency".to_string(),
        scope: result.test_case_id.clone(),
        severity: Severity::Error,
        message: format!(
            "Analyzer verdict '{verdict}' is inconsistent with step evidence (expected '{expected}')"
        ),
        corrected_verdict: Some(expected.to_string()),
    })
}
