import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from qa_agent.config import Settings, get_effective_settings
from qa_agent.rag.client import get_qdrant_client
from qa_agent.rag.embeddings import get_embeddings
from qa_agent.rag.models import RetrievedDoc, SimilarBug
from qa_agent.rate_limiter import enforce_limit_async, enforce_limit_sync

# Embeddings are hardcoded to Google regardless of llm_provider (see
# rag/embeddings.py), so the limiter scope is fixed here too -- update this
# to f"{provider}:embedding" if embeddings ever become provider-selectable.
_EMBEDDING_SCOPE = "google:embedding"

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


class RagService:
    """Thin wrapper around a Qdrant client + an embeddings model.

    Always construct and use this directly rather than checking for a
    client/embeddings being present at call sites -- `enabled` captures
    that, and the read methods (`retrieve_docs`/`find_similar_bugs`) never
    raise: they return `[]` when RAG isn't configured or when the
    underlying call fails (e.g. the collection doesn't exist yet). The
    write methods (`upsert_docs`/`upsert_bugs`) are the one exception --
    ingestion is an explicit user action, so they raise when disabled.
    """

    def __init__(
        self,
        client: "QdrantClient | None",
        embeddings: "Embeddings | None",
        settings: Settings,
    ):
        self._client = client
        self._embeddings = embeddings
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._client is not None and self._embeddings is not None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "RagService":
        settings = settings or get_effective_settings()
        return cls(get_qdrant_client(settings), get_embeddings(settings), settings)

    async def retrieve_docs(self, query: str, top_k: int | None = None) -> list[RetrievedDoc]:
        if self._client is None or self._embeddings is None:
            return []
        top_k = top_k or self._settings.rag_docs_top_k
        # Deliberately outside the try/except below: a DailyQuotaExceededError
        # is a policy decision, not a RAG infra failure, so it should
        # propagate rather than be swallowed as "continuing without context".
        await enforce_limit_async(_EMBEDDING_SCOPE, self._settings)
        try:
            vector = await self._embeddings.aembed_query(query)
            response = await asyncio.to_thread(
                self._client.query_points,
                collection_name=self._settings.qdrant_docs_collection,
                query=vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            logger.warning("RAG doc retrieval failed; continuing without context", exc_info=True)
            return []
        return [
            RetrievedDoc(
                text=(point.payload or {}).get("text", ""),
                source=(point.payload or {}).get("source", "unknown"),
                score=point.score,
            )
            for point in response.points
        ]

    async def find_similar_bugs(self, query: str, top_k: int | None = None) -> list[SimilarBug]:
        if self._client is None or self._embeddings is None:
            return []
        top_k = top_k or self._settings.rag_bugs_top_k
        await enforce_limit_async(_EMBEDDING_SCOPE, self._settings)
        try:
            vector = await self._embeddings.aembed_query(query)
            response = await asyncio.to_thread(
                self._client.query_points,
                collection_name=self._settings.qdrant_bugs_collection,
                query=vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            logger.warning("RAG bug lookup failed; continuing without known-bug context", exc_info=True)
            return []
        return [
            SimilarBug(
                id=(point.payload or {}).get("id", str(point.id)),
                title=(point.payload or {}).get("title", ""),
                description=(point.payload or {}).get("description", ""),
                severity=(point.payload or {}).get("severity", "unknown"),
                score=point.score,
            )
            for point in response.points
        ]

    def upsert_docs(self, chunks: list[tuple[str, str]]) -> int:
        """`chunks` is a list of (text, source) pairs. Returns the number
        of chunks written."""
        if self._client is None or self._embeddings is None:
            raise RuntimeError(
                "RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY."
            )
        if not chunks:
            return 0

        from qdrant_client.models import PointStruct

        enforce_limit_sync(_EMBEDDING_SCOPE, self._settings)
        vectors = self._embeddings.embed_documents([text for text, _ in chunks])
        points = [
            PointStruct(id=str(uuid4()), vector=vector, payload={"text": text, "source": source})
            for vector, (text, source) in zip(vectors, chunks, strict=True)
        ]
        self._client.upsert(collection_name=self._settings.qdrant_docs_collection, points=points)
        return len(points)

    def upsert_bugs(self, bugs: list[dict]) -> int:
        """`bugs` is a list of {id?, title, description, severity} dicts.
        Returns the number of bugs written."""
        if self._client is None or self._embeddings is None:
            raise RuntimeError(
                "RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY."
            )
        if not bugs:
            return 0

        from qdrant_client.models import PointStruct

        texts = [f"{bug['title']}\n{bug['description']}" for bug in bugs]
        enforce_limit_sync(_EMBEDDING_SCOPE, self._settings)
        vectors = self._embeddings.embed_documents(texts)
        points = [
            PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={
                    "id": bug.get("id") or f"BUG-SEED-{i:03d}",
                    "title": bug["title"],
                    "description": bug["description"],
                    "severity": bug.get("severity", "unknown"),
                },
            )
            for i, (vector, bug) in enumerate(zip(vectors, bugs, strict=True))
        ]
        self._client.upsert(collection_name=self._settings.qdrant_bugs_collection, points=points)
        return len(points)
