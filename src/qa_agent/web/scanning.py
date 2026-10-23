"""Pure filesystem helpers for the web UI -- no Flask/app-context
dependency, so these are unit-testable on their own. Deliberately
tolerant of partial/corrupt files (a run directory can be mid-write, or a
generated script's sidecar can be missing): skip, don't crash the page."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from qa_agent.report.models import QAReport

logger = logging.getLogger(__name__)


@dataclass
class ReportSummary:
    run_id: str
    target_url: str
    overall_status: str
    started_at: str
    finished_at: str
    test_case_count: int
    bug_count: int


def scan_reports(reports_dir: Path) -> list[ReportSummary]:
    summaries: list[ReportSummary] = []
    for report_path in Path(reports_dir).glob("*/report.json"):
        try:
            report = QAReport.model_validate_json(report_path.read_text())
        except Exception:
            logger.warning("Skipping unparseable report at %s", report_path, exc_info=True)
            continue
        summaries.append(
            ReportSummary(
                run_id=report.run_id,
                target_url=report.target_url,
                overall_status=report.overall_status,
                started_at=report.started_at,
                finished_at=report.finished_at,
                test_case_count=len(report.test_results),
                bug_count=len(report.bugs),
            )
        )
    summaries.sort(key=lambda s: s.started_at, reverse=True)
    return summaries


def load_report(reports_dir: Path, run_id: str) -> QAReport | None:
    report_path = Path(reports_dir) / run_id / "report.json"
    if not report_path.is_file():
        return None
    try:
        return QAReport.model_validate_json(report_path.read_text())
    except Exception:
        logger.warning("Could not parse report at %s", report_path, exc_info=True)
        return None


@dataclass
class ScriptInfo:
    path: Path
    run_id: str
    test_case_id: str
    title: str
    target_url: str


def scan_generated_scripts(reports_dir: Path, generated_tests_dirname: str) -> list[ScriptInfo]:
    scripts: list[ScriptInfo] = []
    pattern = f"*/{generated_tests_dirname}/*.py"
    for script_path in sorted(Path(reports_dir).glob(pattern)):
        sidecar_path = script_path.with_suffix(".json")
        if not sidecar_path.is_file():
            continue
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except Exception:
            logger.warning("Skipping script with unparseable sidecar at %s", sidecar_path, exc_info=True)
            continue
        run_id = script_path.parent.parent.name
        try:
            scripts.append(
                ScriptInfo(
                    path=script_path,
                    run_id=run_id,
                    test_case_id=sidecar["test_case_id"],
                    title=sidecar["title"],
                    target_url=sidecar.get("target_url", ""),
                )
            )
        except KeyError:
            logger.warning("Skipping script with incomplete sidecar at %s", sidecar_path, exc_info=True)
    return scripts
