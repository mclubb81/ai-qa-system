from functools import lru_cache
from typing import TYPE_CHECKING

from qa_agent.config import Settings, get_effective_settings

if TYPE_CHECKING:
    from qdrant_client import QdrantClient


@lru_cache
def _build_client(url: str, api_key: str) -> "QdrantClient":
    from qdrant_client import QdrantClient

    return QdrantClient(url=url, api_key=api_key)


def get_qdrant_client(settings: Settings | None = None) -> "QdrantClient | None":
    """Lazily build a Qdrant client, or return None if Qdrant isn't
    configured. Never raises -- callers (RagService) are responsible for
    treating None as "RAG disabled".

    Caches on (url, api_key) rather than the Settings object itself, since
    pydantic settings instances aren't hashable.
    """
    settings = settings or get_effective_settings()
    if not (settings.qdrant_url and settings.qdrant_api_key):
        return None
    return _build_client(settings.qdrant_url, settings.qdrant_api_key)
