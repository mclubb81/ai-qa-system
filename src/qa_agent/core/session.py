import traceback
from pathlib import Path

from pydantic import BaseModel

from qa_agent.config import get_effective_settings
from qa_agent.db.log_service import LogService
from qa_agent.db.prompt_service import PromptService
from qa_agent.graph.build import build_graph
from qa_agent.graph.state import Bug, GeneratedScript, QAState, TestCaseResult
from qa_agent.llm import resolve_llm_provider_and_model
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.mcp.playwright_client import PlaywrightMCPSession
from qa_agent.prompts.analyzer import ANALYZER_SYSTEM_PROMPT
from qa_agent.prompts.codegen import CODEGEN_SYSTEM_PROMPT
from qa_agent.prompts.executor import EXECUTOR_SYSTEM_PROMPT
from qa_agent.prompts.planner import PLANNER_SYSTEM_PROMPT
from qa_agent.prompts.triage import TRIAGE_SYSTEM_PROMPT
from qa_agent.rag.service import RagService
from qa_agent.report.writer import overall_status
from qa_agent.utils.ids import new_run_id, now_iso

_PROMPTED_NODE_DEFAULTS = {
    "planner": PLANNER_SYSTEM_PROMPT,
    "executor": EXECUTOR_SYSTEM_PROMPT,
    "analyzer": ANALYZER_SYSTEM_PROMPT,
    "triage": TRIAGE_SYSTEM_PROMPT,
    "codegen": CODEGEN_SYSTEM_PROMPT,
}


class RunResult(BaseModel):
    run_id: str
    overall_status: str
    report_markdown_path: str | None
    report_json_path: str | None
    test_results: list[TestCaseResult]
    bugs: list[Bug]
    generated_scripts: list[GeneratedScript]


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
    generate_regression_scripts: bool = False,
) -> RunResult:
    """Public library entrypoint. The CLI is a thin wrapper over this --
    a future API/UI layer can call it directly instead."""
    run_id = new_run_id()
    run_dir = Path(reports_dir) / run_id
    screenshot_dir = run_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    effective_settings = get_effective_settings()
    # Used both for QAState.llm_provider/llm_model (log_run_start/CLI
    # display) and to force the router onto this one provider for the
    # whole run when the caller passed an explicit provider/model --
    # otherwise each node's actual per-attempt provider/model comes from
    # the router's candidate selection, which may fail over mid-run.
    resolved_provider, resolved_model = resolve_llm_provider_and_model(provider, model, effective_settings)
    router = ModelRouter.from_settings(effective_settings, provider=provider, model=model)
    rag_service = RagService.from_settings(effective_settings)
    log_service = LogService.from_settings(effective_settings)
    prompt_service = PromptService.from_settings(effective_settings)
    # Snapshot of each prompted node's active version at run start, for
    # the runs.prompt_versions column -- an external consumer (e.g. a
    # remote RL loop) can join this to run outcomes without re-deriving it
    # from llm_calls. None for a node still on its hardcoded default.
    prompt_versions = {
        node_name: prompt_service.get_active_version(node_name, default)[1]
        for node_name, default in _PROMPTED_NODE_DEFAULTS.items()
    }

    started_at = now_iso()
    initial_state: QAState = {
        "run_id": run_id,
        "target_url": target_url,
        "requirements_raw": requirements,
        "llm_provider": resolved_provider,
        "llm_model": resolved_model,
        "screenshot_dir": str(screenshot_dir),
        "max_retries": max_retries,
        "retry_counts": {},
        "retrieved_docs": None,
        "test_plan": None,
        "test_results": [],
        "bugs": [],
        "errors": [],
        "generated_scripts": [],
        "generate_regression_scripts": generate_regression_scripts,
        "verified_test_case_ids": [],
        "pipeline_verified": False,
        "verification_violations": [],
        "started_at": started_at,
        "report_markdown_path": None,
        "report_json_path": None,
    }

    await log_service.log_run_start(
        run_id,
        target_url,
        requirements[:300],
        resolved_provider,
        resolved_model,
        started_at,
        prompt_versions=prompt_versions,
    )

    final_state: QAState | None = None
    run_error: str | None = None
    try:
        async with PlaywrightMCPSession(headless=headless) as session:
            graph = build_graph(
                router, session.tools, rag_service, log_service, prompt_service, effective_settings
            )

            final_state = await graph.ainvoke(
                initial_state, config={"recursion_limit": recursion_limit}
            )
    except Exception as exc:
        run_error = str(exc)
        await log_service.log_error(run_id, None, str(exc), traceback.format_exc())
        raise
    finally:
        if final_state is not None:
            await log_service.log_run_end(
                run_id,
                overall_status(final_state),
                len(final_state["bugs"]),
                len(final_state["test_results"]),
                now_iso(),
            )
        else:
            await log_service.log_run_end(run_id, "error", 0, 0, now_iso(), error=run_error)

    # Unreachable when an exception was raised above (the `raise` re-propagates
    # before this line), so final_state is always set here -- this just makes
    # that invariant explicit for the type checker.
    assert final_state is not None
    return RunResult(
        run_id=run_id,
        overall_status=overall_status(final_state),
        report_markdown_path=final_state["report_markdown_path"],
        report_json_path=final_state["report_json_path"],
        test_results=final_state["test_results"],
        bugs=final_state["bugs"],
        generated_scripts=final_state["generated_scripts"],
    )
