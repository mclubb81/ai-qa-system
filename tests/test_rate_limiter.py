from uuid import uuid4

import pytest

from qa_agent.config import Settings
from qa_agent.rate_limiter import (
    DailyQuotaExceededError,
    _effective_rpm,
    _loop_a_controllers,
    enforce_limit_async,
    enforce_limit_sync,
    record_call_outcome,
)


def _settings(limits: dict) -> Settings:
    return Settings(provider_limits=limits)


def _scope() -> str:
    # Rate-limiter state is module-level/global, so each test uses its own
    # scope key to stay isolated from the others.
    return f"test-{uuid4()}:chat"


async def test_unconfigured_scope_is_noop(monkeypatch):
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("should not sleep for an unconfigured scope")

    monkeypatch.setattr("qa_agent.rate_limiter.asyncio.sleep", _fail_if_called)

    await enforce_limit_async(_scope(), _settings({}))


async def test_under_rpm_limit_does_not_wait(monkeypatch):
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("should not sleep while under the rpm limit")

    monkeypatch.setattr("qa_agent.rate_limiter.asyncio.sleep", _fail_if_called)

    scope = _scope()
    settings = _settings({scope: {"rpm": 5}})
    await enforce_limit_async(scope, settings)
    await enforce_limit_async(scope, settings)


async def test_rpm_limit_waits_for_the_window_to_clear(monkeypatch):
    waits: list[float] = []

    async def _record_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("qa_agent.rate_limiter.asyncio.sleep", _record_sleep)

    scope = _scope()
    settings = _settings({scope: {"rpm": 1}})
    await enforce_limit_async(scope, settings)
    await enforce_limit_async(scope, settings)

    assert len(waits) == 1
    assert 0 < waits[0] <= 60


async def test_rpd_limit_raises_without_waiting(monkeypatch):
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("a daily quota breach should fail fast, not sleep")

    monkeypatch.setattr("qa_agent.rate_limiter.asyncio.sleep", _fail_if_called)

    scope = _scope()
    settings = _settings({scope: {"rpd": 1}})
    await enforce_limit_async(scope, settings)

    with pytest.raises(DailyQuotaExceededError):
        await enforce_limit_async(scope, settings)


def test_sync_rpm_limit_waits_for_the_window_to_clear(monkeypatch):
    waits: list[float] = []

    monkeypatch.setattr("qa_agent.rate_limiter.time.sleep", lambda seconds: waits.append(seconds))

    scope = _scope()
    settings = _settings({scope: {"rpm": 1}})
    enforce_limit_sync(scope, settings)
    enforce_limit_sync(scope, settings)

    assert len(waits) == 1
    assert 0 < waits[0] <= 60


def test_sync_rpd_limit_raises_without_waiting(monkeypatch):
    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("a daily quota breach should fail fast, not sleep")

    monkeypatch.setattr("qa_agent.rate_limiter.time.sleep", _fail_if_called)

    scope = _scope()
    settings = _settings({scope: {"rpd": 1}})
    enforce_limit_sync(scope, settings)

    with pytest.raises(DailyQuotaExceededError):
        enforce_limit_sync(scope, settings)


# -- Loop A: adaptive rate limiting -----------------------------------


def test_record_call_outcome_is_noop_for_scope_with_no_rpm_ceiling():
    scope = _scope()
    settings = _settings({scope: {"max_output_tokens": 1024}})  # no "rpm" key
    record_call_outcome(scope, settings, hit_rate_limit=True)
    assert scope not in _loop_a_controllers


def test_repeated_rate_limit_hits_narrow_the_effective_rpm():
    scope = _scope()
    settings = Settings(
        provider_limits={scope: {"rpm": 10}},
        loop_a_pid_gains={"kp": 5.0, "ki": 0.0, "kd": 0.0},
        loop_a_min_multiplier=0.1,
    )

    assert _effective_rpm(scope, 10) == 10  # no controller yet -> unchanged

    for _ in range(5):
        record_call_outcome(scope, settings, hit_rate_limit=True)

    assert _effective_rpm(scope, 10) < 10


def test_clean_calls_never_push_the_effective_rpm_above_the_ceiling():
    scope = _scope()
    settings = Settings(provider_limits={scope: {"rpm": 10}})

    for _ in range(5):
        record_call_outcome(scope, settings, hit_rate_limit=False)

    # Output is clamped to output_max=1.0, so a run of clean calls can
    # only ever keep the multiplier at the ceiling, never exceed it.
    assert _effective_rpm(scope, 10) == 10
