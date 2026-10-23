from functools import lru_cache
from typing import TYPE_CHECKING

from qa_agent.config import Settings, get_effective_settings

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings


@lru_cache
def _build_embeddings(model: str, api_key: str) -> "Embeddings":
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(model=model, google_api_key=api_key)


def get_embeddings(settings: Settings | None = None) -> "Embeddings | None":
    """Lazily build a Google text-embedding-004 client, or return None if no
    Google API key is configured. Never raises.

    Caches on (model, api_key) rather than the Settings object itself, since
    pydantic settings instances aren't hashable.
    """
    settings = settings or get_effective_settings()
    if not settings.google_api_key:
        return None
    return _build_embeddings(settings.rag_embedding_model, settings.google_api_key)
