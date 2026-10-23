from conftest import _StubAsyncPool

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService


def _settings() -> Settings:
    return Settings()


async def test_every_log_method_is_a_noop_when_disabled():
    service = LogService(None, _settings())
    # None of these should raise, even though nothing is configured.
    await service.log_run_start("run-1", "https://example.com", "reqs", "groq", "model", "2026-01-01T00:00:00Z")
    await service.log_run_end("run-1", "pass", 0, 1, "2026-01-01T00:00:01Z")
    await service.log_node_transition("run-1", "planner", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", 10.0)
    await service.log_llm_call("run-1", "planner", "groq", "model", "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", 10.0, 100, 50)
    await service.log_error("run-1", "planner", "boom")


async def test_log_run_start_writes_through_when_enabled():
    pool = _StubAsyncPool()
    service = LogService(pool, _settings())

    await service.log_run_start("run-1", "https://example.com", "reqs", "groq", "model", "2026-01-01T00:00:00Z")

    assert pool.open_calls == 1
    # First call also pays for the one-time schema-ensure DDL execute.
    assert len(pool.executed) == 2
    sql, params = pool.executed[-1]
    assert "INSERT INTO runs" in sql
    assert params[0] == "run-1"


async def test_all_log_methods_write_through_when_enabled():
    pool = _StubAsyncPool()
    service = LogService(pool, _settings())

    await service.log_run_start("run-1", "https://example.com", "reqs", "groq", "model", "t0")
    await service.log_run_end("run-1", "pass", 0, 1, "t1")
    await service.log_node_transition("run-1", "planner", "t0", "t1", 10.0)
    await service.log_llm_call("run-1", "planner", "groq", "model", "t0", "t1", 10.0, 100, 50)
    await service.log_error("run-1", "planner", "boom")

    # One schema-ensure DDL execute (first call only) + one execute per log call.
    assert len(pool.executed) == 6
    # Schema + pool are only opened/ensured once across all five calls.
    assert pool.open_calls == 1


async def test_write_failure_is_swallowed_and_does_not_raise():
    pool = _StubAsyncPool(fail=True)
    service = LogService(pool, _settings())

    # Should not raise despite every execute() failing.
    await service.log_run_start("run-1", "https://example.com", "reqs", "groq", "model", "t0")
    await service.log_error("run-1", None, "boom")


async def test_ensure_ready_disables_permanently_after_open_failure():
    pool = _StubAsyncPool(fail_on_open=True)
    service = LogService(pool, _settings())

    await service.log_run_start("run-1", "https://example.com", "reqs", "groq", "model", "t0")
    assert pool.open_calls == 1
    assert service.enabled is False

    # A second call must not retry opening the (now-abandoned) pool.
    await service.log_error("run-1", None, "boom")
    assert pool.open_calls == 1
