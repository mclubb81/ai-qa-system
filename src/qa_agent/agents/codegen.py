import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import GeneratedScript, QAState
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.prompts.codegen import CODEGEN_SYSTEM_PROMPT

# Truncated the same way agents/executor.py truncates individual tool-call
# results (_summarize_tool_message) -- defends against a pathologically
# long transcript blowing out the prompt/cost budget.
_TRANSCRIPT_CHAR_LIMIT = 6000


class CodegenResponse(BaseModel):
    script: str


def build_codegen_user_message(
    test_case_id: str,
    title: str,
    target_url: str,
    step_descriptions: list[str],
    transcript: list[dict],
) -> str:
    """Builds the Generator's input prompt from a test case's steps and its
    raw Playwright MCP tool-call transcript. Pure function, reused verbatim
    by both the codegen node and Healer (agents/healer.py)."""
    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(step_descriptions))
    transcript_text = json.dumps(transcript, indent=2)[:_TRANSCRIPT_CHAR_LIMIT]
    return (
        f"Target URL: {target_url}\n"
        f"Test case: {test_case_id} - {title}\n"
        f"Steps that passed, in order:\n{steps_text}\n\n"
        "Raw tool-call transcript from the passing run (ref values are "
        "ephemeral accessibility-tree ids from that one run's snapshot and "
        "MUST NOT be used as Playwright locators -- derive role/text-based "
        "locators from each call's human-readable `element` description "
        f"instead):\n{transcript_text}"
    )


def write_generated_script(
    run_dir: Path,
    dirname: str,
    test_case_id: str,
    title: str,
    target_url: str,
    step_descriptions: list[str],
    script_text: str,
) -> GeneratedScript:
    """Writes `<test_case_id>.py` + a `<test_case_id>.json` sidecar (the
    metadata Healer needs to re-validate this script later, independent of
    any particular run's QAState) under `run_dir/dirname`. Reused by both
    the codegen node and Healer."""
    scripts_dir = run_dir / dirname
    scripts_dir.mkdir(parents=True, exist_ok=True)

    script_path = scripts_dir / f"{test_case_id}.py"
    sidecar_path = scripts_dir / f"{test_case_id}.json"

    script_path.write_text(script_text)
    sidecar_path.write_text(
        json.dumps(
            {
                "test_case_id": test_case_id,
                "title": title,
                "target_url": target_url,
                "steps": step_descriptions,
            },
            indent=2,
        )
    )

    return GeneratedScript(
        test_case_id=test_case_id,
        title=title,
        script_path=f"{dirname}/{test_case_id}.py",
        sidecar_path=f"{dirname}/{test_case_id}.json",
    )


def make_codegen_node(
    router: ModelRouter, log_service: LogService, settings: Settings
) -> Callable[[QAState], Awaitable[dict]]:
    async def codegen_node(state: QAState) -> dict:
        codegen_ids = {g.test_case_id for g in state["generated_scripts"]}
        result = next(
            r
            for r in state["test_results"]
            if r.verdict == "pass" and r.test_case_id not in codegen_ids
        )

        step_descriptions = [s.description for s in result.steps]
        transcript = result.steps[0].tool_calls if result.steps else []
        user_message = build_codegen_user_message(
            result.test_case_id, result.title, state["target_url"], step_descriptions, transcript
        )

        def build_call(llm: BaseChatModel) -> Callable[[], Awaitable[Any]]:
            structured_llm = llm.with_structured_output(CodegenResponse)
            return lambda: structured_llm.ainvoke(
                [SystemMessage(content=CODEGEN_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            )

        response: CodegenResponse = await router.call_with_selection(
            "codegen",
            build_call,
            run_id=state["run_id"],
            log_service=log_service,
            settings=settings,
            prompt_chars=len(user_message),
        )

        run_dir = Path(state["screenshot_dir"]).parent
        generated = write_generated_script(
            run_dir,
            settings.generated_tests_dirname,
            result.test_case_id,
            result.title,
            state["target_url"],
            step_descriptions,
            response.script,
        )
        return {"generated_scripts": [*state["generated_scripts"], generated]}

    return codegen_node
