from pathlib import Path

from qa_agent.graph.state import (
    Bug,
    GeneratedScript,
    QAState,
    StepResult,
    TestCaseResult,
)
from qa_agent.report.json_writer import write_json
from qa_agent.report.markdown import render_markdown
from qa_agent.report.models import QAReport
from qa_agent.report.writer import overall_status, write_report


def _sample_report() -> QAReport:
    result = TestCaseResult(
        test_case_id="TC-01",
        title="Page loads",
        priority="high",
        steps=[StepResult(description="Navigate", status="pass", screenshot_path="screenshots/TC-01-1.png")],
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:05Z",
        verdict="fail",
        reasoning="Title was missing",
        suspected_bug=True,
    )
    bug = Bug(
        id="BUG-01",
        title="Missing page title",
        severity="medium",
        related_test_case_id="TC-01",
        repro_steps=["Navigate to the page"],
        expected="A title should be present",
        actual="No title element found",
        suspected_root_cause="Template missing <title> tag",
        screenshot_refs=["screenshots/TC-01-1.png"],
        repro_script_path="generated_tests/BUG-01_repro.py",
    )
    generated_script = GeneratedScript(
        test_case_id="TC-02",
        title="Checkout flow",
        script_path="generated_tests/TC-02.py",
        sidecar_path="generated_tests/TC-02.json",
    )
    return QAReport(
        run_id="20260101T000000Z",
        target_url="https://example.com",
        requirements_summary="Check the page loads and has a title",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:10Z",
        overall_status="fail",
        test_results=[result],
        bugs=[bug],
        generated_scripts=[generated_script],
    )


def test_render_markdown_contains_table_and_bug():
    md = render_markdown(_sample_report())
    assert "TC-01" in md
    assert "Page loads" in md
    assert "BUG-01" in md
    assert "Missing page title" in md
    assert "screenshots/TC-01-1.png" in md
    assert "generated_tests/BUG-01_repro.py" in md
    assert "generated_tests/TC-02.py" in md


def test_write_json_roundtrip(tmp_path: Path):
    report = _sample_report()
    json_path = tmp_path / "report.json"
    write_json(report, json_path)
    loaded = QAReport.model_validate_json(json_path.read_text())
    assert loaded.run_id == report.run_id
    assert loaded.bugs[0].id == "BUG-01"


def test_write_report_creates_both_files(tmp_path: Path):
    state: QAState = {
        "run_id": "20260101T000000Z",
        "target_url": "https://example.com",
        "requirements_raw": "Check the page loads and has a title",
        "llm_provider": "groq",
        "llm_model": "",
        "screenshot_dir": str(tmp_path / "screenshots"),
        "max_retries": 1,
        "retry_counts": {},
        "test_plan": None,
        "test_results": _sample_report().test_results,
        "bugs": _sample_report().bugs,
        "errors": [],
        "generated_scripts": _sample_report().generated_scripts,
        "started_at": "2026-01-01T00:00:00Z",
        "report_markdown_path": None,
        "report_json_path": None,
    }
    paths = write_report(state, tmp_path)
    assert Path(paths.markdown_path).exists()
    assert Path(paths.json_path).exists()
    assert paths.overall_status == "fail"


def test_overall_status_pass_when_all_pass():
    state: QAState = {
        "test_results": [
            TestCaseResult(
                test_case_id="TC-01",
                title="x",
                priority="high",
                steps=[],
                started_at="2026-01-01T00:00:00Z",
                verdict="pass",
            )
        ]
    }  # type: ignore[typeddict-item]
    assert overall_status(state) == "pass"
