import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel

from qa_agent.config import Settings
from qa_agent.db.config_service import ConfigService
from qa_agent.db.log_service import LogService
from qa_agent.llm import get_llm, resolve_llm_provider_and_model
from qa_agent.llm_logging import logged_llm_call
from qa_agent.llm_router.cost_latency import CostLatencyRouter
from qa_agent.llm_router.provider_errors import is_rate_limit_error
from qa_agent.llm_router.state_store import RouterStateStore
from qa_agent.rate_limiter import DailyQuotaExceededError, record_call_outcome

BuildCall = Callable[[BaseChatModel], Callable[[], Awaitable[Any]]]


class AllProvidersUnavailableError(RuntimeError):
    def __init__(self, node_name: str, candidates: list[str]):
        super().__init__(
            f"Every candidate provider for node {node_name!r} ({candidates}) is "
            f"unavailable for the rest of this run (daily quota reached or "
            f"repeated rate-limit errors)."
        )


class ModelRouter:
    """Owns, for the lifetime of one run: candidate-list resolution per
    node, failover bookkeeping (providers marked unavailable this run),
    the (provider, model) -> BaseChatModel cache, and Loop B (cost/latency
    ranking). Loop A's state lives in rate_limiter.py itself
    (module-level); this class only reports outcomes into it via
    record_call_outcome.
    """

    def __init__(
        self,
        cost_latency: CostLatencyRouter,
        settings: Settings,
        *,
        forced_provider: str | None = None,
        forced_model: str | None = None,
    ):
        self._cost_latency = cost_latency
        self._settings = settings
        # An explicit provider/model (e.g. CLI --provider/--model, or a
        # run_qa_session(provider=..., model=...) caller) takes precedence
        # over node_candidate_providers entirely -- same "explicit override
        # wins" precedence as every other CLI-flag-vs-config knob in this
        # app. It forces every node to that one provider for the whole run
        # (no multi-candidate selection/failover).
        # Lowercased here (not just downstream in resolve_llm_provider_and_
        # model/get_llm) since this value is also used directly as a dict
        # key (provider_limits/scope strings), which are always lowercase.
        self._forced_provider = forced_provider.lower() if forced_provider else None
        self._forced_model = forced_model
        self._llm_cache: dict[tuple[str, str], BaseChatModel] = {}
        self._unavailable: set[str] = set()
        self._consecutive_rate_limit_hits: dict[str, int] = {}

    @classmethod
    def from_settings(
        cls, settings: Settings, *, provider: str | None = None, model: str | None = None
    ) -> "ModelRouter":
        config_service = ConfigService.from_settings(settings)
        return cls(
            CostLatencyRouter(RouterStateStore(config_service), settings),
            settings,
            forced_provider=provider,
            forced_model=model,
        )

    def _candidates(self, node_name: str) -> list[str]:
        if self._forced_provider:
            return [self._forced_provider]
        configured = self._settings.node_candidate_providers.get(node_name)
        return list(configured) if configured else [self._settings.llm_provider]

    def _cached_llm(self, provider: str, model: str) -> BaseChatModel:
        key = (provider, model)
        if key not in self._llm_cache:
            self._llm_cache[key] = get_llm(provider=provider, model=model, settings=self._settings)
        return self._llm_cache[key]

    async def call_with_selection(
        self,
        node_name: str,
        build_call: BuildCall,
        *,
        run_id: str,
        log_service: LogService,
        settings: Settings,
        prompt_chars: int = 0,
    ) -> Any:
        candidates = self._candidates(node_name)
        available = [p for p in candidates if p not in self._unavailable]
        if not available:
            raise AllProvidersUnavailableError(node_name, candidates)

        ranked = await asyncio.to_thread(self._cost_latency.rank, available)

        last_exc: Exception | None = None
        for provider in ranked:
            explicit_model = self._forced_model if provider == self._forced_provider else None
            _, model = resolve_llm_provider_and_model(provider, explicit_model, settings)
            llm = self._cached_llm(provider, model)
            call = build_call(llm)
            scope = f"{provider}:chat"
            started = time.monotonic()
            try:
                response = await logged_llm_call(
                    call,
                    run_id=run_id,
                    node_name=node_name,
                    provider=provider,
                    model=model,
                    log_service=log_service,
                    settings=settings,
                    prompt_chars=prompt_chars,
                )
            except DailyQuotaExceededError as exc:
                self._unavailable.add(provider)
                last_exc = exc
                continue
            except Exception as exc:
                if not is_rate_limit_error(provider, exc):
                    # A genuine bug/auth/validation error is not a
                    # rate/quota problem -- don't mask it behind a silent
                    # provider switch. Let it propagate immediately.
                    raise
                record_call_outcome(scope, settings, hit_rate_limit=True)
                hits = self._consecutive_rate_limit_hits.get(provider, 0) + 1
                self._consecutive_rate_limit_hits[provider] = hits
                if hits >= settings.failover_rate_limit_threshold:
                    self._unavailable.add(provider)
                await asyncio.to_thread(self._cost_latency.record, provider, settings.loop_b_failure_penalty_ms)
                last_exc = exc
                continue

            record_call_outcome(scope, settings, hit_rate_limit=False)
            self._consecutive_rate_limit_hits[provider] = 0
            duration_ms = (time.monotonic() - started) * 1000
            await asyncio.to_thread(self._cost_latency.record, provider, duration_ms)
            return response

        assert last_exc is not None
        raise last_exc
