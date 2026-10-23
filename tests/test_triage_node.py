from qa_agent.agents.triage import TriageResponse, make_triage_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import StepResult, TestCaseResult
from qa_agent.rag.models import SimilarBug

_SETTINGS = Settings()
_DISABLED_LOG_SERVICE = LogService(None, _SETTINGS)


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


class _StubModelRouter:
    """Single-candidate, no-failover fake: just runs build_call against
    the given stub LLM, bypassing routing/PID/failover machinery entirely
    so these tests still verify node behavior given one canned response."""

    def __init__(self, llm):
        self._llm = llm

    async def call_with_selection(self, node_name, build_call, **kwargs):
        return await build_call(self._llm)()


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
        repro_script="from playwright.sync_api import sync_playwright\n# repro\n",
    )


def _flagged_result_with_tool_calls() -> TestCaseResult:
    result = _flagged_result()
    result.steps[0].tool_calls = [
        {"tool_name": "browser_click", "args": {"ref": "e1", "element": "Submit button"}, "result": "ok"}
    ]
    return result


async def test_triage_node_sets_similar_bug_refs_from_rag_results(tmp_path):
    similar = [
        SimilarBug(id="BUG-SEED-001", title="Banner missing", description="...", severity="medium", score=0.8)
    ]
    stub_llm = _StubLLM(_canned_triage())
    node = make_triage_node(_StubModelRouter(stub_llm), _StubRagService(similar), _DISABLED_LOG_SERVICE, _SETTINGS)

    state = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "llm_provider": "groq",
        "llm_model": "",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "bugs": [],
        "test_results": [_flagged_result()],
    }
    update = await node(state)

    bug = update["bugs"][0]
    assert bug.similar_bug_refs == ["BUG-SEED-001"]

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "Banner missing" in user_message


async def test_triage_node_reports_none_found_when_no_similar_bugs(tmp_path):
    stub_llm = _StubLLM(_canned_triage())
    node = make_triage_node(_StubModelRouter(stub_llm), _StubRagService([]), _DISABLED_LOG_SERVICE, _SETTINGS)

    state = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "llm_provider": "groq",
        "llm_model": "",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "bugs": [],
        "test_results": [_flagged_result()],
    }
    update = await node(state)

    bug = update["bugs"][0]
    assert bug.similar_bug_refs == []

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "none found" in user_message


async def test_triage_node_writes_repro_script_and_sets_path(tmp_path):
    stub_llm = _StubLLM(_canned_triage())
    node = make_triage_node(_StubModelRouter(stub_llm), _StubRagService([]), _DISABLED_LOG_SERVICE, _SETTINGS)

    state = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "llm_provider": "groq",
        "llm_model": "",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "bugs": [],
        "test_results": [_flagged_result_with_tool_calls()],
    }
    update = await node(state)

    bug = update["bugs"][0]
    assert bug.repro_script_path == "generated_tests/BUG-01_repro.py"
    repro_path = tmp_path / "generated_tests" / "BUG-01_repro.py"
    assert repro_path.exists()
    assert repro_path.read_text() == _canned_triage().repro_script

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "browser_click" in user_message
    assert "ephemeral accessibility-tree ids" in user_message
