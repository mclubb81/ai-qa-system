//! Assembles the full `VerificationReport` from the structural (`laws`) and
//! oracle (`oracle`) checks for one `/verify` request.

use chrono::Utc;

use crate::model::{VerificationReport, VerifyRequest, Violation};
use crate::{laws, oracle};

pub fn build_report(req: &VerifyRequest) -> VerificationReport {
    let mut violations: Vec<Violation> =
        laws::check_pipeline_composition(&req.test_plan, &req.test_results);

    for result in &req.test_results {
        if let Some(v) = oracle::check_consistency(result) {
            violations.push(v);
        }
    }

    VerificationReport {
        consistent: violations.is_empty(),
        violations,
        checked_at: Utc::now().to_rfc3339(),
    }
}
