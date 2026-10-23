import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph.state import CompiledStateGraph

from qa_agent.agents.codegen import CodegenResponse, build_codegen_user_message
from qa_agent.agents.executor import build_executor_agent, extract_tool_calls
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.mcp.playwright_client import PlaywrightMCPSession
from qa_agent.prompts.codegen import CODEGEN_SYSTEM_PROMPT


@dataclass
class HealResult:
    script_path: Path
    status: Literal["healed", "still_valid", "regression_detected"]
    detail: str


async def heal_script(
    script_path: Path,
    router: ModelRouter,
    log_service: LogService,
    settings: Settings,
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[Any]] | None = None,
) -> HealResult:
    """Re-execute a generated regression script's ORIGINAL steps against the
    live app (re-resolving locators from a fresh accessibility-tree
    snapshot, exactly what Playwright MCP's tools are for) and, if it still
    passes, re-synthesize the script from that fresh transcript. Reads the
    script's JSON sidecar rather than any QAState -- this is a standalone
    operation, independent of the run that originally produced the script.

    If the live re-execution itself fails, that's treated as a genuine app
    regression, not a stale-locator problem -- the file is left untouched
    so the failure surfaces rather than being silently papered over.
    """
    sidecar_path = script_path.with_suffix(".json")
    if not sidecar_path.exists():
        raise FileNotFoundError(f"No sidecar metadata found at {sidecar_path}")

    sidecar = json.loads(sidecar_path.read_text())
    test_case_id: str = sidecar["test_case_id"]
    title: str = sidecar["title"]
    target_url: str = sidecar["target_url"]
    step_descriptions: list[str] = sidecar["steps"]

    if session_factory is None:
        def session_factory() -> AbstractAsyncContextManager[Any]:
            return PlaywrightMCPSession(headless=settings.playwright_headless)

    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(step_descriptions))
    user_message = (
        f"Target URL: {target_url}\n"
        f"Test case: {test_case_id} - {title}\n"
        f"Steps to execute, in order:\n{steps_text}"
    )
    run_id = f"heal-{test_case_id}"

    async with session_factory() as session:
        agent_cache: dict[int, CompiledStateGraph] = {}

        def build_executor_call(llm: BaseChatModel):
            if id(llm) not in agent_cache:
                agent_cache[id(llm)] = build_executor_agent(llm, session.tools)
            agent = agent_cache[id(llm)]
            return lambda: agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config={"recursion_limit": 50},
            )

        result = await router.call_with_selection(
            "healer",
            build_executor_call,
            run_id=run_id,
            log_service=log_service,
            settings=settings,
            prompt_chars=len(user_message),
        )
        messages = result["messages"]
        structured = result["structured_response"]
        fresh_transcript = extract_tool_calls(messages)

        failed = [s for s in structured.steps if s.status == "fail"]
        if failed:
            return HealResult(
                script_path,
                "regression_detected",
                detail=(
                    f"Live re-execution failed at step: {failed[0].description} "
                    f"({failed[0].error or 'no error detail'})"
                ),
            )

        codegen_user_message = build_codegen_user_message(
            test_case_id, title, target_url, step_descriptions, fresh_transcript
        )

        def build_codegen_call(llm: BaseChatModel):
            structured_llm = llm.with_structured_output(CodegenResponse)
            return lambda: structured_llm.ainvoke(
                [
                    SystemMessage(content=CODEGEN_SYSTEM_PROMPT),
                    HumanMessage(content=codegen_user_message),
                ]
            )

        codegen_response: CodegenResponse = await router.call_with_selection(
            "healer",
            build_codegen_call,
            run_id=run_id,
            log_service=log_service,
            settings=settings,
            prompt_chars=len(codegen_user_message),
        )

    old_script = script_path.read_text()
    if codegen_response.script.strip() == old_script.strip():
        return HealResult(
            script_path, "still_valid", detail="Re-execution succeeded; no script changes needed."
        )

    script_path.write_text(codegen_response.script)
    return HealResult(
        script_path, "healed", detail="Locators re-resolved from a fresh live run; script updated."
    )


async def heal_many(
    targets: list[Path], router: ModelRouter, log_service: LogService, settings: Settings
) -> list[HealResult]:
    """Heal several scripts in sequence (one live browser session each, so
    running them concurrently wouldn't actually be faster). Shared by the
    CLI's `heal --all` and the web UI's healer page."""
    return [await heal_script(target, router, log_service, settings) for target in targets]
