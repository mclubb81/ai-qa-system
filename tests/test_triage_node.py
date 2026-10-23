from qa_agent.agents.triage import TriageResponse, make_triage_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import StepResult, TestCaseResult
from qa_agent.rag.models import SimilarBug

_DISABLED_LOG_SERVICE = LogService(None, Settings())


class _StubStructuredLLM:
    def __init__(self, response):
        self._response = response
        self.last_messages = None

    async def ainvoke(self, messages):
        self.last_messages = messages
        return self._response


class _StubLLM:
    def __init__(self, response):
        self._response = response
        self.structured_llm = None

    def with_structured_output(self, schema):
        self.structured_llm = _StubStructuredLLM(self._response)
        return self.structured_llm


class _StubRagService:
    def __init__(self, similar_bugs):
        self._similar_bugs = similar_bugs

    async def find_similar_bugs(self, query, top_k=None):
        return self._similar_bugs


def _flagged_result() -> TestCaseResult:
    return TestCaseResult(
        test_case_id="TC-01",
        title="Sign-up works",
        priority="high",
        steps=[StepResult(description="Submit form", status="fail", error="Timeout")],
        started_at="2026-01-01T00:00:00Z",
        verdict="fail",
        reasoning="The confirmation banner never appeared.",
        suspected_bug=True,
    )


def _canned_triage() -> TriageResponse:
    return TriageResponse(
        title="Confirmation banner missing",
        severity="medium",
        repro_steps=["Submit the sign-up form"],
        expected="A confirmation banner appears",
        actual="No banner appears",
        suspected_root_cause="Possibly a rendering race condition",
    )


async def test_triage_node_sets_similar_bug_refs_from_rag_results():
    similar = [
        SimilarBug(id="BUG-SEED-001", title="Banner missing", description="...", severity="medium", score=0.8)
    ]
    stub_llm = _StubLLM(_canned_triage())
    node = make_triage_node(stub_llm, _StubRagService(similar), _DISABLED_LOG_SERVICE)

    state = {
        "run_id": "test-run",
        "llm_provider": "groq",
        "llm_model": "",
        "bugs": [],
        "test_results": [_flagged_result()],
    }
    update = await node(state)

    bug = update["bugs"][0]
    assert bug.similar_bug_refs == ["BUG-SEED-001"]

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "Banner missing" in user_message


async def test_triage_node_reports_none_found_when_no_similar_bugs():
    stub_llm = _StubLLM(_canned_triage())
    node = make_triage_node(stub_llm, _StubRagService([]), _DISABLED_LOG_SERVICE)

    state = {
        "run_id": "test-run",
        "llm_provider": "groq",
        "llm_model": "",
        "bugs": [],
        "test_results": [_flagged_result()],
    }
    update = await node(state)

    bug = update["bugs"][0]
    assert bug.similar_bug_refs == []

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "none found" in user_message
