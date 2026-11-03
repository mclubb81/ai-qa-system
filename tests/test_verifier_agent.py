import httpx
import pytest

from qa_agent.agents.verifier import make_verifier_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import StepResult, TestCase, TestCaseResult

_SETTINGS = Settings()
_DISABLED_LOG_SERVICE = LogService(None, _SETTINGS)


class _StubVerifierClient:
    """Stands in for the Rust service over HTTP -- no network, no API keys."""

    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    async def verify(self, payload: dict) -> dict:
        if self._error is not None:
            raise self._error
        return self._response


def _test_case() -> TestCase:
    return TestCase(id="TC-01", title="Page loads", priority="high", steps=["Navigate"])


def _result(verdict: str = "pass", step_status: str = "pass") -> TestCaseResult:
    return TestCaseResult(
        test_case_id="TC-01",
        title="Page loads",
        priority="high",
        steps=[StepResult(description="Navigate", status=step_status)],
        started_at="2026-01-01T00:00:00Z",
        verdict=verdict,
    )


def _state(test_results, **overrides) -> dict:
    state = {
        "run_id": "test-run",
        "test_plan": [_test_case()],
        "test_results": test_results,
        "verified_test_case_ids": [],
        "pipeline_verified": False,
        "verification_violations": [],
    }
    state.update(overrides)
    return state


async def test_no_violations_marks_everything_verified():
    node = make_verifier_node(
        _SETTINGS, _DISABLED_LOG_SERVICE, client=_StubVerifierClient({"violations": []})
    )
    state = _state([_result()])

    update = await node(state)

    assert update["pipeline_verified"] is True
    assert update["verified_test_case_ids"] == ["TC-01"]
    assert update["verification_violations"] == []
    assert update["test_results"][0].verdict == "pass"


async def test_functor_violation_corrects_the_verdict():
    violation = {
        "law": "functor_consistency",
        "scope": "TC-01",
        "severity": "error",
        "message": "mismatch",
        "corrected_verdict": "fail",
    }
    node = make_verifier_node(
        _SETTINGS, _DISABLED_LOG_SERVICE, client=_StubVerifierClient({"violations": [violation]})
    )
    state = _state([_result(verdict="pass", step_status="fail")])

    update = await node(state)

    corrected = update["test_results"][0]
    assert corrected.verdict == "fail"
    assert corrected.suspected_bug is True
    assert "verdict corrected by verifier" in corrected.reasoning
    assert len(update["verification_violations"]) == 1


async def test_fail_open_on_transport_error_by_default():
    node = make_verifier_node(
        _SETTINGS,
        _DISABLED_LOG_SERVICE,
        client=_StubVerifierClient(error=httpx.ConnectError("boom")),
    )
    state = _state([_result()])

    update = await node(state)

    assert update["pipeline_verified"] is True
    assert update["verified_test_case_ids"] == ["TC-01"]
    assert update["verification_violations"] == []


async def test_fail_closed_reraises_instead_of_swallowing():
    settings = Settings(verifier_fail_closed=True)
    node = make_verifier_node(
        settings,
        _DISABLED_LOG_SERVICE,
        client=_StubVerifierClient(error=httpx.ConnectError("boom")),
    )
    state = _state([_result()])

    with pytest.raises(httpx.ConnectError):
        await node(state)


async def test_disabled_verifier_is_a_noop_passthrough():
    settings = Settings(verifier_enabled=False)
    node = make_verifier_node(settings, _DISABLED_LOG_SERVICE, client=_StubVerifierClient())
    state = _state([_result()])

    update = await node(state)

    assert update["pipeline_verified"] is True
    assert update["verified_test_case_ids"] == ["TC-01"]
    assert update["verification_violations"] == []
