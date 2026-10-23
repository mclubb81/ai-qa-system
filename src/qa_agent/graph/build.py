import time
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path

from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from qa_agent.agents.analyzer import make_analyzer_node
from qa_agent.agents.executor import make_executor_node
from qa_agent.agents.planner import make_planner_node
from qa_agent.agents.retriever import make_retriever_node
from qa_agent.agents.triage import make_triage_node
from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.graph.router import route
from qa_agent.graph.state import NodeName, QAState
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.rag.service import RagService
from qa_agent.report.writer import write_report
from qa_agent.utils.ids import now_iso


def _make_report_node():
    async def report_node(state: QAState) -> dict:
        run_dir = Path(state["screenshot_dir"]).parent
        paths = write_report(state, run_dir)
        return {
            "report_markdown_path": paths.markdown_path,
            "report_json_path": paths.json_path,
        }

    return report_node


def _with_node_logging(
    name: str, fn: Callable[[QAState], Awaitable[dict]], log_service: LogService
) -> Callable[[QAState], Awaitable[dict]]:
    """Wrap a node so every traversal is timed and recorded, and any
    exception escaping the node is logged before being re-raised. This is
    the single error-logging boundary for the graph -- it never swallows,
    so the CLI still surfaces real tracebacks and exits non-zero."""

    async def wrapped(state: QAState) -> dict:
        started_at = now_iso()
        started = time.monotonic()
        try:
            result = await fn(state)
        except Exception as exc:
            duration_ms = (time.monotonic() - started) * 1000
            await log_service.log_node_transition(
                state["run_id"], name, started_at, now_iso(), duration_ms, ok=False
            )
            await log_service.log_error(state["run_id"], name, str(exc), traceback.format_exc())
            raise
        duration_ms = (time.monotonic() - started) * 1000
        await log_service.log_node_transition(
            state["run_id"], name, started_at, now_iso(), duration_ms, ok=True
        )
        return result

    return wrapped


def build_graph(
    router: ModelRouter,
    tools: list[BaseTool],
    rag_service: RagService,
    log_service: LogService,
    settings: Settings,
) -> CompiledStateGraph:
    """Wire the Coordinator-routed graph.

    `router` (a ModelRouter) owns provider/model selection -- including
    failover and cost/latency-based ranking -- so every LLM-calling node
    (including executor) is built from it here, rather than from one
    shared `llm` instance. `tools` are the live Playwright MCP tools,
    passed through to the executor node, which builds its ReAct agent
    fresh per candidate provider attempt (see agents/executor.py).

    `rag_service` is always a real `RagService` instance, never None --
    when RAG isn't configured it just returns empty results, so the
    retriever/triage nodes need no special-casing here. Same for
    `log_service`: always real, logging is simply a no-op when unconfigured.
    """
    graph = StateGraph(QAState)
    graph.add_node("retriever", _with_node_logging("retriever", make_retriever_node(rag_service), log_service))
    graph.add_node(
        "planner",
        _with_node_logging("planner", make_planner_node(router, log_service, settings), log_service),
    )
    graph.add_node(
        "executor",
        _with_node_logging(
            "executor", make_executor_node(router, tools, log_service, settings), log_service
        ),
    )
    graph.add_node(
        "analyzer",
        _with_node_logging("analyzer", make_analyzer_node(router, log_service, settings), log_service),
    )
    graph.add_node(
        "triage",
        _with_node_logging(
            "triage", make_triage_node(router, rag_service, log_service, settings), log_service
        ),
    )
    graph.add_node("report", _with_node_logging("report", _make_report_node(), log_service))

    route_map: dict[NodeName, str] = {
        "retriever": "retriever",
        "planner": "planner",
        "executor": "executor",
        "analyzer": "analyzer",
        "triage": "triage",
        "report": "report",
    }

    graph.set_conditional_entry_point(route, route_map)
    for node in ("retriever", "planner", "executor", "analyzer", "triage"):
        graph.add_conditional_edges(node, route, route_map)
    graph.add_edge("report", END)

    return graph.compile()
