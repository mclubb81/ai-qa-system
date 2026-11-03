import qa_agent.agents.executor as executor_module
from qa_agent.agents.executor import build_executor_agent
from qa_agent.prompts.executor import EXECUTOR_SYSTEM_PROMPT


def _patch_create_agent(monkeypatch):
    captured = {}

    def fake_create_agent(llm, tools, system_prompt=None, response_format=None):
        captured["llm"] = llm
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        return "compiled-graph-stub"

    monkeypatch.setattr(executor_module, "create_agent", fake_create_agent)
    return captured


def test_build_executor_agent_passes_through_custom_system_prompt(monkeypatch):
    captured = _patch_create_agent(monkeypatch)

    result = build_executor_agent("stub-llm", [], system_prompt="CUSTOM EXECUTOR PROMPT")

    assert captured["system_prompt"] == "CUSTOM EXECUTOR PROMPT"
    assert result == "compiled-graph-stub"


def test_build_executor_agent_defaults_to_hardcoded_prompt(monkeypatch):
    captured = _patch_create_agent(monkeypatch)

    build_executor_agent("stub-llm", [])

    assert captured["system_prompt"] == EXECUTOR_SYSTEM_PROMPT
