from pathlib import Path

from pydantic import BaseModel

from qa_agent.agents.executor import build_executor_agent, make_executor_node
from qa_agent.graph.build import build_graph
from qa_agent.graph.state import Bug, QAState, TestCaseResult
from qa_agent.llm import get_llm
from qa_agent.mcp.playwright_client import PlaywrightMCPSession
from qa_agent.rag.service import RagService
from qa_agent.report.writer import overall_status
from qa_agent.utils.ids import new_run_id, now_iso


class RunResult(BaseModel):
    run_id: str
    overall_status: str
    report_markdown_path: str | None
    report_json_path: str | None
    test_results: list[TestCaseResult]
    bugs: list[Bug]


async def run_qa_session(
    *,
    target_url: str,
    requirements: str,
    provider: str | None = None,
    model: str | None = None,
    headless: bool = True,
    max_retries: int = 1,
    reports_dir: str | Path = "reports",
    recursion_limit: int = 250,
) -> RunResult:
    """Public library entrypoint. The CLI is a thin wrapper over this --
    a future API/UI layer can call it directly instead."""
    run_id = new_run_id()
    run_dir = Path(reports_dir) / run_id
    screenshot_dir = run_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    llm = get_llm(provider=provider, model=model)
    rag_service = RagService.from_settings()

    initial_state: QAState = {
        "run_id": run_id,
        "target_url": target_url,
        "requirements_raw": requirements,
        "llm_provider": provider or "",
        "llm_model": model or "",
        "screenshot_dir": str(screenshot_dir),
        "max_retries": max_retries,
        "retry_counts": {},
        "retrieved_docs": None,
        "test_plan": None,
        "test_results": [],
        "bugs": [],
        "errors": [],
        "started_at": now_iso(),
        "report_markdown_path": None,
        "report_json_path": None,
    }

    async with PlaywrightMCPSession(headless=headless) as session:
        executor_agent = build_executor_agent(llm, session.tools)
        executor_node = make_executor_node(executor_agent)
        graph = build_graph(executor_node, llm, rag_service)

        final_state: QAState = await graph.ainvoke(
            initial_state, config={"recursion_limit": recursion_limit}
        )

    return RunResult(
        run_id=run_id,
        overall_status=overall_status(final_state),
        report_markdown_path=final_state["report_markdown_path"],
        report_json_path=final_state["report_json_path"],
        test_results=final_state["test_results"],
        bugs=final_state["bugs"],
    )
