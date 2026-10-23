from collections.abc import Awaitable, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from qa_agent.graph.state import QAState, TestCase
from qa_agent.prompts.planner import PLANNER_SYSTEM_PROMPT


class TestPlanResponse(BaseModel):
    test_cases: list[TestCase] = Field(default_factory=list)


def make_planner_node(
    llm: BaseChatModel,
) -> Callable[[QAState], Awaitable[dict]]:
    structured_llm = llm.with_structured_output(TestPlanResponse)

    async def planner_node(state: QAState) -> dict:
        user_message = (
            f"Target URL: {state['target_url']}\n\n"
            f"Requirements:\n{state['requirements_raw']}"
        )
        response: TestPlanResponse = await structured_llm.ainvoke(
            [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=user_message)]
        )
        return {"test_plan": response.test_cases}

    return planner_node
