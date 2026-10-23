from functools import lru_cache

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
