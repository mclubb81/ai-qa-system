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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
