from dataclasses import dataclass
from pathlib import Path

from qa_agent.graph.state import QAState
from qa_agent.report.json_writer import write_json
from qa_agent.report.markdown import render_markdown
from qa_agent.report.models import QAReport
from qa_agent.utils.ids import now_iso


@dataclass
class ReportPaths:
    markdown_path: str
    json_path: str
    overall_status: str


def overall_status(state: QAState) -> str:
    verdicts = {r.verdict for r in state["test_results"]}
    if "fail" in verdicts:
        return "fail"
    if verdicts == {"pass"}:
        return "pass"
    return "fail" if not verdicts else "flaky"


def write_report(state: QAState, run_dir: Path) -> ReportPaths:
    status = overall_status(state)
    report = QAReport(
        run_id=state["run_id"],
        target_url=state["target_url"],
        requirements_summary=state["requirements_raw"][:300],
        started_at=state["started_at"],
        finished_at=now_iso(),
        overall_status=status,
        test_results=state["test_results"],
        bugs=state["bugs"],
    )

    markdown_path = run_dir / "report.md"
    json_path = run_dir / "report.json"
    markdown_path.write_text(render_markdown(report))
    write_json(report, json_path)

    return ReportPaths(
        markdown_path=str(markdown_path),
        json_path=str(json_path),
        overall_status=status,
    )
