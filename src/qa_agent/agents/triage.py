from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from qa_agent.db.log_service import LogService
from qa_agent.graph.state import Bug, QAState
from qa_agent.llm_logging import logged_llm_call
from qa_agent.prompts.triage import TRIAGE_SYSTEM_PROMPT
from qa_agent.rag.service import RagService


class TriageResponse(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    repro_steps: list[str]
    expected: str
    actual: str
    suspected_root_cause: str


def make_triage_node(
    llm: BaseChatModel, rag_service: RagService, log_service: LogService
) -> Callable[[QAState], Awaitable[dict]]:
    structured_llm = llm.with_structured_output(TriageResponse)

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

        user_message = (
            f"Test case: {result.test_case_id} - {result.title}\n"
            f"Analyzer reasoning: {result.reasoning}\n"
            f"Step results:\n{steps_text}"
            f"{similar_block}"
        )
        triage: TriageResponse = await logged_llm_call(
            lambda: structured_llm.ainvoke(
                [SystemMessage(content=TRIAGE_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            ),
            run_id=state["run_id"],
            node_name="triage",
            provider=state["llm_provider"],
            model=state["llm_model"],
            log_service=log_service,
            prompt_chars=len(user_message),
        )

        screenshot_refs = [step.screenshot_path for step in result.steps if step.screenshot_path]
        bug = Bug(
            id=f"BUG-{len(state['bugs']) + 1:02d}",
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
        return {"bugs": [*state["bugs"], bug]}

    return triage_node
