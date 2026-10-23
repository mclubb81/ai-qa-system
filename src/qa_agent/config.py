from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: str = "groq"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    google_api_key: str | None = None
    google_model: str = "gemini-2.5-flash"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    playwright_headless: bool = True
    reports_dir: str = "reports"
    max_retries: int = 1

    # RAG (optional) -- grounds the Planner in indexed docs and lets Triage
    # look up similar known bugs. Leave unset to run without RAG.
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_docs_collection: str = "qa_docs"
    qdrant_bugs_collection: str = "qa_bugs"

    # Embeddings use Google text-embedding-004 -- reuses google_api_key above.
    rag_embedding_model: str = "models/text-embedding-004"
    rag_docs_top_k: int = 5
    rag_bugs_top_k: int = 3

    # Postgres (bootstrap-only -- these can't themselves live in the config
    # DB, since you need them to find it).
    qa_logs_database_url: str | None = None
    qa_config_database_url: str | None = None

    # Cost/rate controls, keyed by "<provider>:chat" or "<provider>:embedding"
    # so e.g. Google's chat and embedding endpoints can have different caps.
    # A scope absent from this map has no cap. These defaults are
    # placeholders pulled from each provider's public free-tier docs at
    # write time -- providers change these without notice, which is exactly
    # why the real values belong in the qa_config DB (override the whole
    # map with `qa-agent config set provider_limits '{...}'`), not in code.
    # The mechanism itself isn't free-tier-specific: it's just as useful as
    # a cost cap on a paid plan.
    provider_limits: dict[str, dict[str, int]] = Field(
        default_factory=lambda: {
            "groq:chat": {"rpm": 30, "rpd": 1000, "max_output_tokens": 1024},
            "google:chat": {"rpm": 15, "rpd": 1500, "max_output_tokens": 1024},
            "anthropic:chat": {"rpm": 50, "rpd": 1000, "max_output_tokens": 1024},
            "openai:chat": {"rpm": 60, "rpd": 1000, "max_output_tokens": 1024},
            "google:embedding": {"rpm": 100, "rpd": 1500},
        }
    )

    # Model selection: task-complexity baseline / opt-in candidate lists.
    # Empty dict -> every node falls back to [llm_provider], i.e. today's
    # single-global-provider behavior exactly. Keys are node names
    # ("planner", "analyzer", "triage", "executor"); values are ordered
    # provider-name lists -- most-preferred first, which also serves as
    # the tie-break prior when Loop B (below) has no learned preference.
    node_candidate_providers: dict[str, list[str]] = Field(default_factory=dict)

    # Loop B (model-selection cost/latency weighting): an approximate,
    # admittedly-not-real-dollars relative cost weight per provider, since
    # no actual per-token pricing is tracked anywhere in this codebase.
    # A provider absent from this map gets a neutral weight of 1.0.
    provider_cost_weights: dict[str, float] = Field(default_factory=dict)

    # PID tuning knobs for both adaptive-control loops, externalized like
    # provider_limits since "tuning" implies an operator adjusts these
    # without a code change. Missing keys fall back to in-code defaults.
    loop_a_pid_gains: dict[str, float] = Field(default_factory=dict)
    loop_b_pid_gains: dict[str, float] = Field(default_factory=dict)

    # Loop A (adaptive rate limiting) specifics -- see rate_limiter.py.
    loop_a_target_error_rate: float = 0.05
    loop_a_min_multiplier: float = 0.1
    loop_a_error_rate_ewma_alpha: float = 0.3

    # Model-selection failover: how many consecutive native rate-limit
    # errors from one provider before giving up on it for the rest of
    # this run (a provider merely being throttled might recover, so this
    # is a coarser give-up signal than Loop A's continuous throttling).
    failover_rate_limit_threshold: int = 3

    # Loop B specifics -- see llm_router/cost_latency.py.
    loop_b_failure_penalty_ms: float = 60_000.0
    loop_b_max_dt_seconds: float = 3600.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def rag_enabled(self) -> bool:
        return bool(self.qdrant_url and self.qdrant_api_key and self.google_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_effective_settings(settings: Settings | None = None) -> Settings:
    """Overlay qa_config DB values (if reachable) onto the `.env` bootstrap
    Settings. Falls back to the bootstrap Settings unchanged if the config
    DB is unconfigured/unreachable -- same graceful-degradation contract as
    RagService.enabled. Deliberately uncached: a `config set` must be
    visible on the next call, not frozen behind a stale singleton.

    Note: only keys that match an existing Settings field name actually
    take effect -- model_copy(update=...) will still accept other keys
    (pydantic doesn't validate against the schema here), but they won't
    influence any field lookup elsewhere in the app.
    """
    from qa_agent.db.config_service import ConfigService  # local import: avoids a
                                                            # config.py <-> db cycle

    base = settings or get_settings()
    overrides = ConfigService.from_settings(base).get_all()
    return base.model_copy(update=overrides) if overrides else base
