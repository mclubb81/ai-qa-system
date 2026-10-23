from collections.abc import Awaitable, Callable
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from qa_agent.db.log_service import LogService
from qa_agent.graph.state import QAState
from qa_agent.llm_logging import logged_llm_call
from qa_agent.prompts.analyzer import ANALYZER_SYSTEM_PROMPT


class AnalysisResponse(BaseModel):
    verdict: Literal["pass", "fail", "flaky"]
    reasoning: str
    suspected_bug: bool


def _should_retry(state: QAState, test_case_id: str) -> bool:
    """Deterministic, threshold-based retry decision. Extension point: a
    future version could replace this with an LLM call if retry/re-plan
    decisions need to get smarter than a fixed retry budget."""
    return state["retry_counts"].get(test_case_id, 0) < state["max_retries"]


def make_analyzer_node(llm: BaseChatModel, log_service: LogService) -> Callable[[QAState], Awaitable[dict]]:
    structured_llm = llm.with_structured_output(AnalysisResponse)

    async def analyzer_node(state: QAState) -> dict:
        result = next(r for r in state["test_results"] if r.verdict is None)

        steps_text = "\n".join(
            f"- [{step.status}] {step.description}" + (f" (error: {step.error})" if step.error else "")
            for step in result.steps
        )
        user_message = (
            f"Test case: {result.test_case_id} - {result.title}\n"
            f"Step results:\n{steps_text}"
        )
        analysis: AnalysisResponse = await logged_llm_call(
            lambda: structured_llm.ainvoke(
                [SystemMessage(content=ANALYZER_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            ),
            run_id=state["run_id"],
            node_name="analyzer",
            provider=state["llm_provider"],
            model=state["llm_model"],
            log_service=log_service,
            prompt_chars=len(user_message),
        )

        other_results = [r for r in state["test_results"] if r.test_case_id != result.test_case_id]

        if analysis.verdict == "flaky" and _should_retry(state, result.test_case_id):
            retry_counts = {**state["retry_counts"]}
            retry_counts[result.test_case_id] = retry_counts.get(result.test_case_id, 0) + 1
            # Drop this result so it looks pending again -- the router will
            # naturally send it back to the executor.
            return {"test_results": other_results, "retry_counts": retry_counts}

        result.verdict = analysis.verdict
        result.reasoning = analysis.reasoning
        result.suspected_bug = analysis.suspected_bug
        return {"test_results": [*other_results, result]}

    return analyzer_node
