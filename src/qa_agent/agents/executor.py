import base64
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from qa_agent.db.log_service import LogService
from qa_agent.graph.state import QAState, StepResult, TestCaseResult
from qa_agent.llm_logging import logged_llm_call
from qa_agent.prompts.executor import EXECUTOR_SYSTEM_PROMPT
from qa_agent.utils.ids import now_iso


class StepOutcome(BaseModel):
    description: str
    status: Literal["pass", "fail"]
    error: str | None = None
    screenshot_taken: bool = False


class ExecutionReport(BaseModel):
    steps: list[StepOutcome] = Field(default_factory=list)


def build_executor_agent(llm: BaseChatModel, tools: list[BaseTool]) -> CompiledStateGraph:
    """Build the ReAct agent that drives Playwright MCP tools for one test case.

    This is the only agent with browser tools bound to it -- Planner,
    Analyzer and Triage each make a single structured-output LLM call with
    no tools.
    """
    return create_agent(
        llm,
        tools,
        system_prompt=EXECUTOR_SYSTEM_PROMPT,
        response_format=ExecutionReport,
    )


def _summarize_tool_message(message: ToolMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content[:500]
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, dict) and block.get("type") == "image":
                parts.append("[image attached]")
        return " ".join(parts)[:500]
    return str(content)[:500]


def extract_tool_calls(messages: list) -> list[dict]:
    """Flatten the raw AIMessage tool_calls + matching ToolMessage results
    into a simple transcript, for traceability."""
    transcript: list[dict] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            for call in message.tool_calls:
                transcript.append({"tool_name": call["name"], "args": call["args"]})
        elif isinstance(message, ToolMessage) and transcript and "result" not in transcript[-1]:
            transcript[-1]["result"] = _summarize_tool_message(message)
    return transcript


def extract_screenshots(messages: list, screenshot_dir: Path, prefix: str) -> list[str]:
    """Decode any image content blocks emitted by tool calls (e.g.
    browser_take_screenshot) and save them under screenshot_dir, returning
    paths relative to the report directory (``screenshots/<file>``), in the
    order they were produced."""
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    refs: list[str] = []
    counter = 0
    for message in messages:
        if not isinstance(message, ToolMessage) or not isinstance(message.content, list):
            continue
        for block in message.content:
            if isinstance(block, dict) and block.get("type") == "image" and block.get("base64"):
                counter += 1
                mime = block.get("mime_type", "image/png")
                ext = "jpg" if "jpeg" in mime else "png"
                filename = f"{prefix}-{counter}.{ext}"
                (screenshot_dir / filename).write_bytes(base64.b64decode(block["base64"]))
                refs.append(f"screenshots/{filename}")
    return refs


def make_executor_node(
    executor_agent: CompiledStateGraph,
    log_service: LogService,
) -> Callable[[QAState], Awaitable[dict]]:
    async def executor_node(state: QAState) -> dict:
        executed_ids = {r.test_case_id for r in state["test_results"]}
        test_case = next(tc for tc in state["test_plan"] if tc.id not in executed_ids)

        steps_text = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(test_case.steps))
        user_message = (
            f"Target URL: {state['target_url']}\n"
            f"Test case: {test_case.id} - {test_case.title}\n"
            f"Steps to execute, in order:\n{steps_text}"
        )

        started_at = now_iso()
        result = await logged_llm_call(
            lambda: executor_agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config={"recursion_limit": 50},
            ),
            run_id=state["run_id"],
            node_name="executor",
            provider=state["llm_provider"],
            model=state["llm_model"],
            log_service=log_service,
            prompt_chars=len(user_message),
        )
        messages = result["messages"]
        structured: ExecutionReport = result["structured_response"]

        screenshot_dir = Path(state["screenshot_dir"])
        screenshot_refs = extract_screenshots(messages, screenshot_dir, prefix=test_case.id)
        tool_calls = extract_tool_calls(messages)

        step_results: list[StepResult] = []
        screenshot_cursor = 0
        for i, outcome in enumerate(structured.steps):
            screenshot_path = None
            if outcome.screenshot_taken and screenshot_cursor < len(screenshot_refs):
                screenshot_path = screenshot_refs[screenshot_cursor]
                screenshot_cursor += 1
            step_results.append(
                StepResult(
                    description=outcome.description,
                    status=outcome.status,
                    # Full raw transcript is attached to the first step only,
                    # to avoid duplicating it across every step of the case.
                    tool_calls=tool_calls if i == 0 else [],
                    error=outcome.error,
                    screenshot_path=screenshot_path,
                )
            )

        test_case_result = TestCaseResult(
            test_case_id=test_case.id,
            title=test_case.title,
            priority=test_case.priority,
            steps=step_results,
            started_at=started_at,
            finished_at=now_iso(),
        )
        return {"test_results": [*state["test_results"], test_case_result]}

    return executor_node
