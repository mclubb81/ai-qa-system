import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from qa_agent.agents.codegen import CodegenResponse
from qa_agent.agents.executor import ExecutionReport, StepOutcome
from qa_agent.agents.healer import heal_script
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService

_SETTINGS = Settings()
_DISABLED_LOG_SERVICE = LogService(None, _SETTINGS)


class _FakeSession:
    def __init__(self):
        self.tools = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _session_factory():
    return _FakeSession()


class _FakeRouter:
    """Dispatches by call order (both under the "healer" node name): the
    first call_with_selection is the live re-execution, the second is the
    codegen re-synthesis. Bypasses build_call entirely -- this exercises
    heal_script's own branching logic, not ModelRouter/build_executor_agent."""

    def __init__(self, executor_result, codegen_response):
        self._executor_result = executor_result
        self._codegen_response = codegen_response
        self.calls = 0

    async def call_with_selection(self, node_name, build_call, **kwargs):
        assert node_name == "healer"
        self.calls += 1
        if self.calls == 1:
            return self._executor_result
        return self._codegen_response


def _passing_executor_result():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "browser_click", "args": {"ref": "e1", "element": "Submit button"}, "id": "1"}
            ],
        ),
        ToolMessage(content="ok", tool_call_id="1"),
    ]
    structured = ExecutionReport(steps=[StepOutcome(description="Submit form", status="pass")])
    return {"messages": messages, "structured_response": structured}


def _failing_executor_result():
    structured = ExecutionReport(
        steps=[StepOutcome(description="Submit form", status="fail", error="Button not found")]
    )
    return {"messages": [], "structured_response": structured}


def _write_script_and_sidecar(tmp_path, script_text):
    script_path = tmp_path / "TC-01.py"
    sidecar_path = tmp_path / "TC-01.json"
    script_path.write_text(script_text)
    sidecar_path.write_text(
        json.dumps(
            {
                "test_case_id": "TC-01",
                "title": "Sign-up works",
                "target_url": "https://example.com",
                "steps": ["Submit form"],
            }
        )
    )
    return script_path


async def test_heal_updates_script_when_regenerated_differs(tmp_path):
    script_path = _write_script_and_sidecar(tmp_path, "old script")
    router = _FakeRouter(_passing_executor_result(), CodegenResponse(script="new script"))

    result = await heal_script(
        script_path, router, _DISABLED_LOG_SERVICE, _SETTINGS, session_factory=_session_factory
    )

    assert result.status == "healed"
    assert script_path.read_text() == "new script"


async def test_heal_reports_still_valid_when_regenerated_matches(tmp_path):
    script_path = _write_script_and_sidecar(tmp_path, "same script")
    router = _FakeRouter(_passing_executor_result(), CodegenResponse(script="same script"))

    result = await heal_script(
        script_path, router, _DISABLED_LOG_SERVICE, _SETTINGS, session_factory=_session_factory
    )

    assert result.status == "still_valid"
    assert script_path.read_text() == "same script"


async def test_heal_detects_regression_on_live_failure(tmp_path):
    script_path = _write_script_and_sidecar(tmp_path, "old script")
    router = _FakeRouter(_failing_executor_result(), CodegenResponse(script="irrelevant"))

    result = await heal_script(
        script_path, router, _DISABLED_LOG_SERVICE, _SETTINGS, session_factory=_session_factory
    )

    assert result.status == "regression_detected"
    assert "Submit form" in result.detail
    assert script_path.read_text() == "old script"


async def test_heal_raises_when_sidecar_missing(tmp_path):
    script_path = tmp_path / "TC-99.py"
    script_path.write_text("x")
    router = _FakeRouter(_passing_executor_result(), CodegenResponse(script="x"))

    with pytest.raises(FileNotFoundError):
        await heal_script(
            script_path, router, _DISABLED_LOG_SERVICE, _SETTINGS, session_factory=_session_factory
        )
