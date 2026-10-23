from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from qa_agent.agents.analyzer import make_analyzer_node
from qa_agent.agents.planner import make_planner_node
from qa_agent.agents.retriever import make_retriever_node
from qa_agent.agents.triage import make_triage_node
from qa_agent.graph.router import route
from qa_agent.graph.state import NodeName, QAState
from qa_agent.rag.service import RagService
from qa_agent.report.writer import write_report


def _make_report_node():
    async def report_node(state: QAState) -> dict:
        run_dir = Path(state["screenshot_dir"]).parent
        paths = write_report(state, run_dir)
        return {
            "report_markdown_path": paths.markdown_path,
            "report_json_path": paths.json_path,
        }

    return report_node


def build_graph(executor_node, llm: BaseChatModel, rag_service: RagService) -> CompiledStateGraph:
    """Wire the Coordinator-routed graph.

    `executor_node` is passed in already built (it closes over the
    executor ReAct agent, which itself closes over the live Playwright MCP
    tools) -- everything else is built here from the shared llm.

    `rag_service` is always a real `RagService` instance, never None --
    when RAG isn't configured it just returns empty results, so the
    retriever/triage nodes need no special-casing here.
    """
    graph = StateGraph(QAState)
    graph.add_node("retriever", make_retriever_node(rag_service))
    graph.add_node("planner", make_planner_node(llm))
    graph.add_node("executor", executor_node)
    graph.add_node("analyzer", make_analyzer_node(llm))
    graph.add_node("triage", make_triage_node(llm, rag_service))
    graph.add_node("report", _make_report_node())

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
