from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from qa_agent.db.log_service import LogService
from qa_agent.graph.state import QAState, TestCase
from qa_agent.llm_logging import logged_llm_call
from qa_agent.prompts.planner import PLANNER_SYSTEM_PROMPT


class TestPlanResponse(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


def make_planner_node(
    llm: BaseChatModel,
    log_service: LogService,
) -> Callable[[QAState], Awaitable[dict]]:
    structured_llm = llm.with_structured_output(TestPlanResponse)

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
        response: TestPlanResponse = await logged_llm_call(
            lambda: structured_llm.ainvoke(
                [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=user_message)]
            ),
            run_id=state["run_id"],
            node_name="planner",
            provider=state["llm_provider"],
            model=state["llm_model"],
            log_service=log_service,
            prompt_chars=len(user_message),
        )
        return {"test_plan": response.test_cases}

    return planner_node
