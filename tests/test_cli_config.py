from typer.testing import CliRunner

import qa_agent.cli as cli_module
from qa_agent.cli import app

runner = CliRunner()


class _StubConfigService:
    def __init__(self, enabled=True, values=None):
        self.enabled = enabled
        self._values = values or {}
        self.set_calls = []

    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_all(self):
        return dict(self._values)

    def set(self, key, value):
        if not self.enabled:
            raise RuntimeError("Config DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        self._values[key] = value
        self.set_calls.append((key, value))


def _patch_config(monkeypatch, stub):
    monkeypatch.setattr(cli_module.ConfigService, "from_settings", classmethod(lambda cls, settings=None: stub))


def test_config_set_stores_json_coerced_value(monkeypatch):
    stub = _StubConfigService(enabled=True)
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "set", "max_retries", "3"])

    assert result.exit_code == 0
    assert stub.set_calls == [("max_retries", 3)]


def test_config_set_falls_back_to_raw_string_when_not_json(monkeypatch):
    stub = _StubConfigService(enabled=True)
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "set", "llm_provider", "google"])

    assert result.exit_code == 0
    assert stub.set_calls == [("llm_provider", "google")]


def test_config_set_fails_clearly_when_disabled(monkeypatch):
    stub = _StubConfigService(enabled=False)
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "set", "max_retries", "3"])

    assert result.exit_code == 1
    assert "not configured" in result.stdout


def test_config_get_prints_value(monkeypatch):
    stub = _StubConfigService(enabled=True, values={"max_retries": 3})
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "get", "max_retries"])

    assert result.exit_code == 0
    assert "3" in result.stdout


def test_config_get_reports_unset_key(monkeypatch):
    stub = _StubConfigService(enabled=True, values={})
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "get", "max_retries"])

    assert result.exit_code == 1
    assert "not set" in result.stdout


def test_config_list_prints_all_values(monkeypatch):
    stub = _StubConfigService(enabled=True, values={"max_retries": 3, "llm_provider": "google"})
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "list"])

    assert result.exit_code == 0
    assert "max_retries = 3" in result.stdout
    assert "llm_provider = google" in result.stdout


def test_config_list_reports_when_disabled(monkeypatch):
    stub = _StubConfigService(enabled=False)
    _patch_config(monkeypatch, stub)

    result = runner.invoke(app, ["config", "list"])

    assert result.exit_code == 1
    assert "not configured" in result.stdout
