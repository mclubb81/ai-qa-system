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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def rag_enabled(self) -> bool:
        return bool(self.qdrant_url and self.qdrant_api_key and self.google_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
