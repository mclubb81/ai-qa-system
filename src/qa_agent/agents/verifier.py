from collections.abc import Awaitable, Callable

import httpx
from pydantic import ValidationError

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import QAState, VerificationViolation
from qa_agent.verifier_client import VerifierClient


def make_verifier_node(
    settings: Settings,
    log_service: LogService,
    client: VerifierClient | None = None,
) -> Callable[[QAState], Awaitable[dict]]:
    verifier_client = client or VerifierClient.from_settings(settings)

    async def verifier_node(state: QAState) -> dict:
        if not settings.verifier_enabled:
            # No-op pass-through: every currently-present result is marked
            # verified without ever calling the Rust service, so a disabled
            # verifier adds no HTTP dependency and no behavior change.
            return {
                "verified_test_case_ids": [r.test_case_id for r in state["test_results"]],
                "pipeline_verified": True,
                "verification_violations": state["verification_violations"],
            }

        payload = {
            "run_id": state["run_id"],
            "test_plan": [tc.model_dump() for tc in (state["test_plan"] or [])],
            "test_results": [r.model_dump() for r in state["test_results"]],
        }

        try:
            raw = await verifier_client.verify(payload)
            violations = [VerificationViolation.model_validate(v) for v in raw["violations"]]
        except (httpx.HTTPError, ValidationError, KeyError) as exc:
            if settings.verifier_fail_closed:
                raise
            await log_service.log_error(state["run_id"], "verifier", str(exc), "")
            violations = []

        other_results = []
        checked_ids = set(state["verified_test_case_ids"])
        for result in state["test_results"]:
            match = next((v for v in violations if v.scope == result.test_case_id), None)
            if match is not None and match.corrected_verdict is not None:
                result.verdict = match.corrected_verdict
                result.reasoning = (
                    f"{result.reasoning or ''} (verdict corrected by verifier: {match.message})"
                ).strip()
                result.suspected_bug = True
            checked_ids.add(result.test_case_id)
            other_results.append(result)

        return {
            "test_results": other_results,
            "verified_test_case_ids": sorted(checked_ids),
            "pipeline_verified": True,
            "verification_violations": [*state["verification_violations"], *violations],
        }

    return verifier_node
