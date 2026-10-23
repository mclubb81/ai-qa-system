import json

import pytest

pytest.importorskip("flask")

from qa_agent.report.models import QAReport
from qa_agent.web.scanning import load_report, scan_generated_scripts, scan_reports


def _write_report(run_dir, run_id, started_at, overall_status="pass"):
    run_dir.mkdir(parents=True, exist_ok=True)
    report = QAReport(
        run_id=run_id,
        target_url="https://example.com",
        requirements_summary="summary",
        started_at=started_at,
        finished_at=started_at,
        overall_status=overall_status,
    )
    (run_dir / "report.json").write_text(report.model_dump_json())


def test_scan_reports_sorts_newest_first_and_skips_malformed(tmp_path):
    _write_report(tmp_path / "run-a", "run-a", "2026-01-01T00:00:00+00:00")
    _write_report(tmp_path / "run-b", "run-b", "2026-02-01T00:00:00+00:00")
    bad_dir = tmp_path / "run-bad"
    bad_dir.mkdir()
    (bad_dir / "report.json").write_text("not json")

    summaries = scan_reports(tmp_path)

    assert [s.run_id for s in summaries] == ["run-b", "run-a"]


def test_load_report_returns_none_for_missing_run(tmp_path):
    assert load_report(tmp_path, "does-not-exist") is None


def test_load_report_returns_parsed_report(tmp_path):
    _write_report(tmp_path / "run-a", "run-a", "2026-01-01T00:00:00+00:00")
    report = load_report(tmp_path, "run-a")
    assert report is not None
    assert report.run_id == "run-a"


def test_scan_generated_scripts_skips_missing_sidecar(tmp_path):
    run_dir = tmp_path / "run-a" / "generated_tests"
    run_dir.mkdir(parents=True)
    (run_dir / "TC-01.py").write_text("# script")
    (run_dir / "TC-01.json").write_text(
        json.dumps(
            {
                "test_case_id": "TC-01",
                "title": "Checkout flow",
                "target_url": "https://example.com",
                "steps": ["step 1"],
            }
        )
    )
    (run_dir / "TC-02.py").write_text("# no sidecar")

    scripts = scan_generated_scripts(tmp_path, "generated_tests")

    assert len(scripts) == 1
    assert scripts[0].test_case_id == "TC-01"
    assert scripts[0].run_id == "run-a"
