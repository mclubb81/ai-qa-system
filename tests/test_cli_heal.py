
from typer.testing import CliRunner

import qa_agent.cli as cli_module
from qa_agent.agents.healer import HealResult
from qa_agent.cli import app
from qa_agent.config import Settings

runner = CliRunner()


def _patch_settings(monkeypatch, **overrides):
    settings = Settings(**overrides)
    monkeypatch.setattr(cli_module, "get_effective_settings", lambda: settings)
    return settings


def _patch_heal_script(monkeypatch, results_by_path):
    async def fake_heal_script(script_path, router, log_service, settings, **kwargs):
        return results_by_path[script_path]

    monkeypatch.setattr(cli_module, "heal_script", fake_heal_script)


def test_heal_requires_script_or_all(monkeypatch):
    _patch_settings(monkeypatch)
    result = runner.invoke(app, ["heal"])
    assert result.exit_code == 1
    assert "--script" in result.stdout


def test_heal_script_prints_healed_and_exits_zero(monkeypatch, tmp_path):
    _patch_settings(monkeypatch)
    script_path = tmp_path / "TC-01.py"
    script_path.write_text("x")
    _patch_heal_script(
        monkeypatch, {script_path: HealResult(script_path, "healed", "locators updated")}
    )

    result = runner.invoke(app, ["heal", "--script", str(script_path)])

    assert result.exit_code == 0
    assert "healed" in result.stdout


def test_heal_script_regression_detected_exits_nonzero(monkeypatch, tmp_path):
    _patch_settings(monkeypatch)
    script_path = tmp_path / "TC-01.py"
    script_path.write_text("x")
    _patch_heal_script(
        monkeypatch, {script_path: HealResult(script_path, "regression_detected", "it broke")}
    )

    result = runner.invoke(app, ["heal", "--script", str(script_path)])

    assert result.exit_code == 1
    assert "regression_detected" in result.stdout


def test_heal_all_discovers_scripts_under_reports_dir(monkeypatch, tmp_path):
    _patch_settings(monkeypatch, generated_tests_dirname="generated_tests")
    run_dir = tmp_path / "20260101T000000Z-abcd1234" / "generated_tests"
    run_dir.mkdir(parents=True)
    script_a = run_dir / "TC-01.py"
    script_b = run_dir / "TC-02.py"
    script_a.write_text("a")
    script_b.write_text("b")

    _patch_heal_script(
        monkeypatch,
        {
            script_a: HealResult(script_a, "still_valid", "no change"),
            script_b: HealResult(script_b, "still_valid", "no change"),
        },
    )

    result = runner.invoke(app, ["heal", "--all", "--reports-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "TC-01.py" in result.stdout
    assert "TC-02.py" in result.stdout


def test_heal_all_reports_none_found(monkeypatch, tmp_path):
    _patch_settings(monkeypatch)
    result = runner.invoke(app, ["heal", "--all", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No generated scripts found" in result.stdout
