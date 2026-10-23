import pytest

pytest.importorskip("flask")

import qa_agent.web.jobs as jobs_module
from qa_agent.web.jobs import JobRegistry, run_async_job


@pytest.fixture(autouse=True)
def _synchronous_spawn(monkeypatch):
    monkeypatch.setattr(jobs_module, "_spawn", lambda fn: fn())


def test_create_starts_queued():
    registry = JobRegistry()
    job = registry.create("run", params={"target_url": "https://example.com"})
    assert job.status == "queued"
    assert registry.get(job.job_id) is job


def test_run_async_job_success_sets_done_with_result():
    registry = JobRegistry()
    job = registry.create("run", params={})

    async def coro():
        return "ok"

    run_async_job(registry, job, lambda: coro())

    assert job.status == "done"
    assert job.result == "ok"
    assert job.started_at is not None
    assert job.finished_at is not None


def test_run_async_job_failure_sets_error():
    registry = JobRegistry()
    job = registry.create("heal", params={})

    async def coro():
        raise RuntimeError("boom")

    run_async_job(registry, job, lambda: coro())

    assert job.status == "error"
    assert job.error == "boom"
    assert job.result is None


def test_get_unknown_job_returns_none():
    registry = JobRegistry()
    assert registry.get("nope") is None
