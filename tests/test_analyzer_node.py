from qa_agent.agents.analyzer import AnalysisResponse, make_analyzer_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import StepResult, TestCaseResult

_DISABLED_LOG_SERVICE = LogService(None, Settings())


class _StubStructuredLLM:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _StubLLM:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _StubStructuredLLM(self._response)


def _pending_result() -> TestCaseResult:
    return TestCaseResult(
        test_case_id="TC-01",
        title="Page loads",
        priority="high",
        steps=[StepResult(description="Navigate", status="fail", error="Timeout")],
        started_at="2026-01-01T00:00:00Z",
        verdict=None,
    )


async def test_analyzer_sets_verdict_on_fail():
    canned = AnalysisResponse(verdict="fail", reasoning="Navigation timed out", suspected_bug=True)
    node = make_analyzer_node(_StubLLM(canned), _DISABLED_LOG_SERVICE)

    state = {
        "run_id": "test-run",
        "llm_provider": "groq",
        "llm_model": "",
        "test_results": [_pending_result()],
        "retry_counts": {},
        "max_retries": 1,
    }
    update = await node(state)

    result = update["test_results"][0]
    assert result.verdict == "fail"
    assert result.suspected_bug is True


async def test_analyzer_requeues_flaky_result_within_retry_budget():
    canned = AnalysisResponse(verdict="flaky", reasoning="Looked like a timing issue", suspected_bug=False)
    node = make_analyzer_node(_StubLLM(canned), _DISABLED_LOG_SERVICE)

    state = {
        "run_id": "test-run",
        "llm_provider": "groq",
        "llm_model": "",
        "test_results": [_pending_result()],
        "retry_counts": {},
        "max_retries": 1,
    }
    update = await node(state)

    # The result is dropped (looks pending again) and retry_counts is bumped.
    assert update["test_results"] == []
    assert update["retry_counts"]["TC-01"] == 1


async def test_analyzer_keeps_flaky_verdict_once_retry_budget_exhausted():
    canned = AnalysisResponse(verdict="flaky", reasoning="Still flaky", suspected_bug=False)
    node = make_analyzer_node(_StubLLM(canned), _DISABLED_LOG_SERVICE)

    state = {
        "run_id": "test-run",
        "llm_provider": "groq",
        "llm_model": "",
        "test_results": [_pending_result()],
        "retry_counts": {"TC-01": 1},
        "max_retries": 1,
    }
    update = await node(state)

    result = update["test_results"][0]
    assert result.verdict == "flaky"
