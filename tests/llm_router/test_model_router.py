import pytest

from qa_agent.config import Settings
from qa_agent.db.log_service import LogService
from qa_agent.llm_router.cost_latency import CostLatencyRouter
from qa_agent.llm_router.model_router import AllProvidersUnavailableError, ModelRouter
from qa_agent.rate_limiter import DailyQuotaExceededError


class _MarkerRateLimitError(Exception):
    """Stands in for a real provider SDK rate-limit exception -- what
    counts as 'a native rate limit error' is monkeypatched per-test via
    qa_agent.llm_router.model_router.is_rate_limit_error, so this test
    file stays decoupled from any actual SDK exception type (that
    classification is covered separately in test_provider_errors.py)."""


class _StubRouterStateStore:
    def __init__(self):
        self._store: dict = {}

    @property
    def enabled(self) -> bool:
        return True

    def get(self, name, default=None):
        return self._store.get(name, default)

    def set(self, name, value) -> None:
        self._store[name] = value


class _StubLLM:
    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model


def _settings(**overrides) -> Settings:
    # provider_limits={} disables Loop A/rpm/rpd entirely -- these tests
    # are about selection/failover logic, not rate limiting (covered in
    # test_rate_limiter.py), and the module-level rate_limiter state is
    # shared/global across the whole test session.
    return Settings(provider_limits={}, **overrides)


def _router(settings: Settings, **kwargs) -> ModelRouter:
    store = _StubRouterStateStore()
    return ModelRouter(CostLatencyRouter(store, settings), settings, **kwargs)


def _disabled_log_service(settings: Settings) -> LogService:
    return LogService(None, settings)


def _patch_get_llm(monkeypatch, calls: list):
    def _fake_get_llm(*, provider, model, settings):
        calls.append((provider, model))
        return _StubLLM(provider, model)

    monkeypatch.setattr("qa_agent.llm_router.model_router.get_llm", _fake_get_llm)


async def test_single_candidate_success_returns_response(monkeypatch):
    settings = _settings(llm_provider="groq")
    calls: list = []
    _patch_get_llm(monkeypatch, calls)
    router = _router(settings)

    def build_call(llm):
        assert isinstance(llm, _StubLLM)
        return lambda: _async_return("ok")

    result = await router.call_with_selection(
        "planner", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    assert result == "ok"
    assert calls == [("groq", "llama-3.3-70b-versatile")]


async def test_failover_on_daily_quota_exceeded(monkeypatch):
    settings = _settings(node_candidate_providers={"analyzer": ["groq", "google"]})
    _patch_get_llm(monkeypatch, [])
    router = _router(settings)

    def build_call(llm):
        if llm.provider == "groq":
            return _raise(DailyQuotaExceededError("groq:chat", 1000))
        return lambda: _async_return("from-google")

    result = await router.call_with_selection(
        "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    assert result == "from-google"

    # groq is now permanently unavailable for the rest of this run -- a
    # second call should go straight to google without retrying groq.
    attempted_providers: list[str] = []

    def build_call_2(llm):
        attempted_providers.append(llm.provider)
        return lambda: _async_return("from-google-again")

    result_2 = await router.call_with_selection(
        "analyzer", build_call_2, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    assert result_2 == "from-google-again"
    assert attempted_providers == ["google"]


async def test_native_rate_limit_error_excludes_provider_after_consecutive_threshold(monkeypatch):
    # A single candidate, so each failed attempt propagates (no fallback
    # to mask it) -- isolates the consecutive-hit counting/threshold
    # behavior from Loop B's ranking (which would otherwise naturally
    # deprioritize a failing provider behind a better-ranked one, meaning
    # it wouldn't even be retried in a multi-candidate setup).
    settings = _settings(node_candidate_providers={"analyzer": ["flaky"]}, failover_rate_limit_threshold=3)
    _patch_get_llm(monkeypatch, [])
    monkeypatch.setattr(
        "qa_agent.llm_router.model_router.is_rate_limit_error",
        lambda provider, exc: isinstance(exc, _MarkerRateLimitError),
    )
    router = _router(settings)

    def build_call(llm):
        return _raise(_MarkerRateLimitError("rate limited"))

    # Below the failover threshold: the error propagates (no candidates
    # left to try), but the provider is not yet permanently excluded.
    for _ in range(2):
        with pytest.raises(_MarkerRateLimitError):
            await router.call_with_selection(
                "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
            )
        assert "flaky" not in router._unavailable

    # The 3rd consecutive hit reaches the threshold -> flaky is excluded
    # going forward.
    with pytest.raises(_MarkerRateLimitError):
        await router.call_with_selection(
            "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
        )
    assert "flaky" in router._unavailable

    # A follow-up call now has no candidates left at all.
    with pytest.raises(AllProvidersUnavailableError):
        await router.call_with_selection(
            "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
        )


async def test_genuine_error_propagates_without_failover(monkeypatch):
    settings = _settings(node_candidate_providers={"analyzer": ["groq", "google"]})
    _patch_get_llm(monkeypatch, [])
    router = _router(settings)

    attempted_providers: list[str] = []

    def build_call(llm):
        attempted_providers.append(llm.provider)
        if llm.provider == "groq":
            return _raise(ValueError("something genuinely broke"))
        return lambda: _async_return("from-google")

    with pytest.raises(ValueError, match="something genuinely broke"):
        await router.call_with_selection(
            "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
        )
    # google must never have been tried -- a real bug isn't a rate/quota
    # problem and must not be masked behind a silent provider switch.
    assert attempted_providers == ["groq"]


async def test_all_providers_unavailable_raises(monkeypatch):
    settings = _settings(node_candidate_providers={"analyzer": ["groq", "google"]})
    _patch_get_llm(monkeypatch, [])
    router = _router(settings)

    def build_call(llm):
        return _raise(DailyQuotaExceededError(f"{llm.provider}:chat", 1000))

    with pytest.raises(DailyQuotaExceededError):
        await router.call_with_selection(
            "analyzer", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
        )

    # Both candidates are now unavailable -- a follow-up call should
    # raise immediately, without attempting build_call at all.
    def build_call_should_not_run(llm):
        raise AssertionError("should never be called -- no candidates left")

    with pytest.raises(AllProvidersUnavailableError):
        await router.call_with_selection(
            "analyzer",
            build_call_should_not_run,
            run_id="r1",
            log_service=_disabled_log_service(settings),
            settings=settings,
        )


async def test_llm_cache_reuses_same_instance_for_same_provider_model(monkeypatch):
    settings = _settings(llm_provider="groq")
    calls: list = []
    _patch_get_llm(monkeypatch, calls)
    router = _router(settings)

    def build_call(llm):
        return lambda: _async_return("ok")

    await router.call_with_selection(
        "planner", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    await router.call_with_selection(
        "planner", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    assert calls == [("groq", "llama-3.3-70b-versatile")]  # only constructed once


async def test_forced_provider_overrides_candidates(monkeypatch):
    settings = _settings(node_candidate_providers={"planner": ["google", "anthropic"]})
    calls: list = []
    _patch_get_llm(monkeypatch, calls)
    router = _router(settings, forced_provider="openai", forced_model="gpt-4o-mini")

    def build_call(llm):
        return lambda: _async_return("from-forced")

    result = await router.call_with_selection(
        "planner", build_call, run_id="r1", log_service=_disabled_log_service(settings), settings=settings
    )
    assert result == "from-forced"
    assert calls == [("openai", "gpt-4o-mini")]


def _raise(exc: Exception):
    async def _thunk():
        raise exc

    return _thunk


async def _async_return(value):
    return value
