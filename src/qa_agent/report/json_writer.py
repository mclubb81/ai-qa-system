from pathlib import Path

from qa_agent.report.models import QAReport


def write_json(report: QAReport, path: Path) -> None:
    path.write_text(report.model_dump_json(indent=2))
