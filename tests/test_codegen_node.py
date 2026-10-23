from qa_agent.agents.codegen import CodegenResponse, make_codegen_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import GeneratedScript, StepResult, TestCaseResult

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
    def __init__(self, llm):
        self._llm = llm

    async def call_with_selection(self, node_name, build_call, **kwargs):
        return await build_call(self._llm)()


def _passed_result() -> TestCaseResult:
    return TestCaseResult(
        test_case_id="TC-01",
        title="Sign-up works",
        priority="high",
        steps=[
            StepResult(
                description="Submit form",
                status="pass",
                tool_calls=[
                    {"tool_name": "browser_click", "args": {"ref": "e1", "element": "Submit button"}, "result": "ok"}
                ],
            )
        ],
        started_at="2026-01-01T00:00:00Z",
        verdict="pass",
    )


def _canned_codegen() -> CodegenResponse:
    return CodegenResponse(script="from playwright.sync_api import sync_playwright\n# regression script\n")


async def test_codegen_node_writes_script_and_sidecar(tmp_path):
    stub_llm = _StubLLM(_canned_codegen())
    node = make_codegen_node(_StubModelRouter(stub_llm), _DISABLED_LOG_SERVICE, _SETTINGS)

    state = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "test_results": [_passed_result()],
        "generated_scripts": [],
    }
    update = await node(state)

    generated: GeneratedScript = update["generated_scripts"][0]
    assert generated.test_case_id == "TC-01"
    assert generated.script_path == "generated_tests/TC-01.py"
    assert generated.sidecar_path == "generated_tests/TC-01.json"

    script_path = tmp_path / "generated_tests" / "TC-01.py"
    sidecar_path = tmp_path / "generated_tests" / "TC-01.json"
    assert script_path.read_text() == _canned_codegen().script
    assert "Submit form" in sidecar_path.read_text()
    assert "https://example.com" in sidecar_path.read_text()

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "browser_click" in user_message
    assert "ephemeral accessibility-tree ids" in user_message


async def test_codegen_node_skips_test_case_already_generated(tmp_path):
    stub_llm = _StubLLM(_canned_codegen())
    node = make_codegen_node(_StubModelRouter(stub_llm), _DISABLED_LOG_SERVICE, _SETTINGS)

    already = GeneratedScript(
        test_case_id="TC-01",
        title="Sign-up works",
        script_path="generated_tests/TC-01.py",
        sidecar_path="generated_tests/TC-01.json",
    )
    other_result = _passed_result()
    other_result.test_case_id = "TC-02"

    state = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "test_results": [_passed_result(), other_result],
        "generated_scripts": [already],
    }
    update = await node(state)

    assert len(update["generated_scripts"]) == 2
    new_ids = {g.test_case_id for g in update["generated_scripts"]}
    assert new_ids == {"TC-01", "TC-02"}
