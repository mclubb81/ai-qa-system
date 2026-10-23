import pytest
from typer.testing import CliRunner

pytest.importorskip("flask")

from qa_agent.cli import app

runner = CliRunner()


class _FakeApp:
    def __init__(self):
        self.run_calls = []

    def run(self, host=None, port=None, debug=None):
        self.run_calls.append({"host": host, "port": port, "debug": debug})


def test_web_launches_flask_app_with_expected_args(monkeypatch):
    fake_app = _FakeApp()

    def fake_create_app():
        return fake_app

    import qa_agent.web.app as web_app_module

    monkeypatch.setattr(web_app_module, "create_app", fake_create_app)

    result = runner.invoke(app, ["web", "--port", "5050"])

    assert result.exit_code == 0
    assert fake_app.run_calls == [{"host": "127.0.0.1", "port": 5050, "debug": False}]


def test_web_refuses_debug_on_non_loopback_host(monkeypatch):
    import qa_agent.web.app as web_app_module

    monkeypatch.setattr(web_app_module, "create_app", lambda: _FakeApp())

    result = runner.invoke(app, ["web", "--host", "0.0.0.0", "--debug"])

    assert result.exit_code == 1
    assert "Refusing" in result.stdout
