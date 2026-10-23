from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.state import QAState, TestCase
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.prompts.planner import PLANNER_SYSTEM_PROMPT


class TestPlanResponse(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


def make_planner_node(
    router: ModelRouter,
    log_service: LogService,
    settings: Settings,
) -> Callable[[QAState], Awaitable[dict]]:
    async def planner_node(state: QAState) -> dict:
        docs = state.get("retrieved_docs") or []
        docs_block = (
            "\n\nRelevant product documentation (retrieved):\n"
            + "\n".join(f"- [{doc.source}] {doc.text}" for doc in docs)
            if docs
            else ""
        )
        user_message = (
            f"Target URL: {state['target_url']}\n\n"
            f"Requirements:\n{state['requirements_raw']}"
            f"{docs_block}"
        )

        def build_call(llm: BaseChatModel) -> Callable[[], Awaitable[Any]]:
            structured_llm = llm.with_structured_output(TestPlanResponse)
            return lambda: structured_llm.ainvoke(
                [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            )

        response: TestPlanResponse = await router.call_with_selection(
            "planner",
            build_call,
            run_id=state["run_id"],
            log_service=log_service,
            settings=settings,
            prompt_chars=len(user_message),
        )
        return {"test_plan": response.test_cases}

    return planner_node
