import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import Bug, QAState
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.prompts.triage import TRIAGE_SYSTEM_PROMPT
from qa_agent.rag.service import RagService

# Same truncation spirit as agents/codegen.py and
# agents/executor.py::_summarize_tool_message -- defends against a
# pathologically long transcript blowing out the prompt/cost budget.
_TRANSCRIPT_CHAR_LIMIT = 6000


class TriageResponse(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    repro_steps: list[str]
    expected: str
    actual: str
    suspected_root_cause: str
    repro_script: str


def make_triage_node(
    router: ModelRouter, rag_service: RagService, log_service: LogService, settings: Settings
) -> Callable[[QAState], Awaitable[dict]]:
    async def triage_node(state: QAState) -> dict:
        triaged_ids = {b.related_test_case_id for b in state["bugs"]}
        result = next(
            r for r in state["test_results"] if r.suspected_bug and r.test_case_id not in triaged_ids
        )

        steps_text = "\n".join(
            f"- [{step.status}] {step.description}" + (f" (error: {step.error})" if step.error else "")
            for step in result.steps
        )

        similar_bugs = await rag_service.find_similar_bugs(f"{result.title}\n{result.reasoning}")
        similar_block = (
            "\n\nSimilar previously known bugs:\n"
            + "\n".join(f"- [{b.severity}] {b.title}: {b.description}" for b in similar_bugs)
            if similar_bugs
            else "\n\nSimilar previously known bugs: none found."
        )

        transcript = result.steps[0].tool_calls if result.steps else []
        transcript_block = (
            "\n\nRaw tool-call transcript from the failing run (for "
            "repro-script synthesis; `ref` values are ephemeral "
            "accessibility-tree ids from that one run's snapshot and MUST "
            "NOT be used as Playwright locators -- derive role/text-based "
            "locators from each call's human-readable `element` description "
            f"instead):\n{json.dumps(transcript, indent=2)[:_TRANSCRIPT_CHAR_LIMIT]}"
        )

        user_message = (
            f"Test case: {result.test_case_id} - {result.title}\n"
            f"Target URL: {state['target_url']}\n"
            f"Analyzer reasoning: {result.reasoning}\n"
            f"Step results:\n{steps_text}"
            f"{similar_block}"
            f"{transcript_block}"
        )

        def build_call(llm: BaseChatModel) -> Callable[[], Awaitable[Any]]:
            structured_llm = llm.with_structured_output(TriageResponse)
            return lambda: structured_llm.ainvoke(
                [SystemMessage(content=TRIAGE_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            )

        triage: TriageResponse = await router.call_with_selection(
            "triage",
            build_call,
            run_id=state["run_id"],
            log_service=log_service,
            settings=settings,
            prompt_chars=len(user_message),
        )

        screenshot_refs = [step.screenshot_path for step in result.steps if step.screenshot_path]
        bug_id = f"BUG-{len(state['bugs']) + 1:02d}"
        bug = Bug(
            id=bug_id,
            title=triage.title,
            severity=triage.severity,
            related_test_case_id=result.test_case_id,
            repro_steps=triage.repro_steps,
            expected=triage.expected,
            actual=triage.actual,
            suspected_root_cause=triage.suspected_root_cause,
            screenshot_refs=screenshot_refs,
            similar_bug_refs=[b.id for b in similar_bugs],
        )

        run_dir = Path(state["screenshot_dir"]).parent
        scripts_dir = run_dir / settings.generated_tests_dirname
        scripts_dir.mkdir(parents=True, exist_ok=True)
        repro_filename = f"{bug_id}_repro.py"
        (scripts_dir / repro_filename).write_text(triage.repro_script)
        bug.repro_script_path = f"{settings.generated_tests_dirname}/{repro_filename}"

        return {"bugs": [*state["bugs"], bug]}

    return triage_node
