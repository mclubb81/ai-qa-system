import io
import json

import pytest

pytest.importorskip("flask")

import qa_agent.web.jobs as jobs_module
import qa_agent.web.routes as routes_module
from qa_agent.agents.healer import HealResult
from qa_agent.config import Settings
from qa_agent.core.session import RunResult
from qa_agent.web.app import create_app


@pytest.fixture(autouse=True)
def _synchronous_spawn(monkeypatch):
    monkeypatch.setattr(jobs_module, "_spawn", lambda fn: fn())


@pytest.fixture
def client():
    return create_app().test_client()


class _StubConfigService:
    def __init__(self, enabled=True, values=None):
        self.enabled = enabled
        self._values = values or {}
        self.set_calls = []
        self.delete_calls = []

    def get(self, key, default=None):
        return self._values.get(key, default)

    def get_all(self):
        return dict(self._values)

    def set(self, key, value):
        self._values[key] = value
        self.set_calls.append((key, value))

    def delete(self, key):
        self._values.pop(key, None)
        self.delete_calls.append(key)

    @classmethod
    def from_settings(cls, settings=None):
        return cls._instance


def _patch_settings(monkeypatch, tmp_path, **overrides):
    settings = Settings(reports_dir=str(tmp_path), **overrides)
    monkeypatch.setattr(routes_module, "get_settings", lambda: settings)
    monkeypatch.setattr(routes_module, "get_effective_settings", lambda *a, **k: settings)
    return settings


def test_index_loads(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"New Run" in resp.data


def test_new_run_get_renders_form(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    resp = client.get("/runs/new")
    assert resp.status_code == 200
    assert b"Target URL" in resp.data


def test_new_run_post_success_redirects_to_job_and_links_report(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)

    fake_result = RunResult(
        run_id="run-123",
        overall_status="pass",
        report_markdown_path=None,
        report_json_path=None,
        test_results=[],
        bugs=[],
        generated_scripts=[],
    )

    async def fake_run_qa_session(**kwargs):
        return fake_result

    monkeypatch.setattr(routes_module, "run_qa_session", fake_run_qa_session)

    resp = client.post(
        "/runs/new",
        data={"url": "https://example.com", "requirements_text": "do the thing"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert b"done" in resp.data
    assert b"/reports/run-123" in resp.data


def test_new_run_post_failure_shows_error(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)

    async def fake_run_qa_session(**kwargs):
        raise RuntimeError("playwright exploded")

    monkeypatch.setattr(routes_module, "run_qa_session", fake_run_qa_session)

    resp = client.post(
        "/runs/new",
        data={"url": "https://example.com", "requirements_text": "do the thing"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert b"playwright exploded" in resp.data


def test_new_run_post_requires_url_and_requirements(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    resp = client.post("/runs/new", data={"url": "", "requirements_text": ""}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"required" in resp.data


def test_new_run_post_accepts_uploaded_requirements_file(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    captured = {}

    async def fake_run_qa_session(**kwargs):
        captured.update(kwargs)
        return RunResult(
            run_id="run-456",
            overall_status="pass",
            report_markdown_path=None,
            report_json_path=None,
            test_results=[],
            bugs=[],
            generated_scripts=[],
        )

    monkeypatch.setattr(routes_module, "run_qa_session", fake_run_qa_session)

    resp = client.post(
        "/runs/new",
        data={
            "url": "https://example.com",
            "requirements_text": "",
            "requirements_file": (io.BytesIO(b"from a file"), "reqs.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert captured["requirements"] == "from a file"


def test_job_status_api_unknown_job_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]


def test_reports_list_and_detail(client, monkeypatch, tmp_path):
    from qa_agent.report.models import QAReport

    _patch_settings(monkeypatch, tmp_path)
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    report = QAReport(
        run_id="run-a",
        target_url="https://example.com",
        requirements_summary="summary",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:05:00+00:00",
        overall_status="pass",
    )
    (run_dir / "report.json").write_text(report.model_dump_json())

    list_resp = client.get("/reports")
    assert list_resp.status_code == 200
    assert b"run-a" in list_resp.data

    detail_resp = client.get("/reports/run-a")
    assert detail_resp.status_code == 200
    assert b"example.com" in detail_resp.data

    missing_resp = client.get("/reports/does-not-exist")
    assert missing_resp.status_code == 404


def test_config_get_shows_disabled_banner(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    stub = _StubConfigService(enabled=False)
    monkeypatch.setattr(_StubConfigService, "_instance", stub, raising=False)
    monkeypatch.setattr(routes_module, "ConfigService", _StubConfigService)

    resp = client.get("/config")
    assert resp.status_code == 200
    assert b"not configured" in resp.data


def test_config_post_sets_fields_and_skips_masked_and_empty(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    stub = _StubConfigService(enabled=True)
    monkeypatch.setattr(_StubConfigService, "_instance", stub, raising=False)
    monkeypatch.setattr(routes_module, "ConfigService", _StubConfigService)

    resp = client.post(
        "/config",
        data={
            "max_retries": "3",
            "groq_api_key": routes_module.MASK,
            "openai_api_key": "",
            "llm_provider": "google",
        },
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert ("max_retries", 3) in stub.set_calls
    assert ("llm_provider", "google") in stub.set_calls
    assert not any(key == "groq_api_key" for key, _ in stub.set_calls)
    assert not any(key == "openai_api_key" for key, _ in stub.set_calls)


def test_config_post_delete_clears_field(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    stub = _StubConfigService(enabled=True, values={"max_retries": 5})
    monkeypatch.setattr(_StubConfigService, "_instance", stub, raising=False)
    monkeypatch.setattr(routes_module, "ConfigService", _StubConfigService)

    resp = client.post("/config", data={"delete_max_retries": "on"}, follow_redirects=True)

    assert resp.status_code == 200
    assert "max_retries" in stub.delete_calls


def test_config_post_rejected_when_disabled(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    stub = _StubConfigService(enabled=False)
    monkeypatch.setattr(_StubConfigService, "_instance", stub, raising=False)
    monkeypatch.setattr(routes_module, "ConfigService", _StubConfigService)

    resp = client.post("/config", data={"max_retries": "3"})
    assert resp.status_code == 400


def test_config_post_bad_json_field_flashes_and_skips(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    stub = _StubConfigService(enabled=True)
    monkeypatch.setattr(_StubConfigService, "_instance", stub, raising=False)
    monkeypatch.setattr(routes_module, "ConfigService", _StubConfigService)

    resp = client.post(
        "/config", data={"provider_limits": "{not valid json"}, follow_redirects=True
    )

    assert resp.status_code == 200
    assert b"not valid JSON" in resp.data
    assert not any(key == "provider_limits" for key, _ in stub.set_calls)


def _write_script(reports_dir, run_id, test_case_id, title="Checkout"):
    run_dir = reports_dir / run_id / "generated_tests"
    run_dir.mkdir(parents=True, exist_ok=True)
    script_path = run_dir / f"{test_case_id}.py"
    script_path.write_text("# script")
    (run_dir / f"{test_case_id}.json").write_text(
        json.dumps(
            {
                "test_case_id": test_case_id,
                "title": title,
                "target_url": "https://example.com",
                "steps": ["step 1"],
            }
        )
    )
    return script_path


def test_healer_get_lists_discovered_scripts(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    _write_script(tmp_path, "run-a", "TC-01")

    resp = client.get("/healer")
    assert resp.status_code == 200
    assert b"TC-01" in resp.data


def test_healer_post_heals_selected_script(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    script_path = _write_script(tmp_path, "run-a", "TC-01")

    async def fake_heal_many(targets, router, log_service, settings):
        return [HealResult(targets[0], "healed", "locators updated")]

    monkeypatch.setattr(routes_module, "heal_many", fake_heal_many)

    resp = client.post(
        "/healer", data={"script": str(script_path.resolve())}, follow_redirects=True
    )

    assert resp.status_code == 200
    assert b"healed" in resp.data


def test_healer_post_rejects_path_outside_reports_dir(client, monkeypatch, tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    _patch_settings(monkeypatch, reports_dir)
    outside = tmp_path / "evil.py"
    outside.write_text("# not a real script")

    resp = client.post("/healer", data={"script": str(outside.resolve())})
    assert resp.status_code == 400


def test_healer_post_requires_selection(client, monkeypatch, tmp_path):
    _patch_settings(monkeypatch, tmp_path)
    resp = client.post("/healer", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Select at least one" in resp.data
