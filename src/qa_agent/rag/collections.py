from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

VECTOR_SIZE = 768  # Google text-embedding-004


def ensure_collection(client: "QdrantClient", name: str, vector_size: int = VECTOR_SIZE) -> None:
    """Create the collection if it doesn't already exist. Only called from
    CLI ingestion paths -- the read path (RagService.retrieve_docs /
    find_similar_bugs) never writes, so a missing collection there is just
    treated as "no results"."""
    from qdrant_client.models import Distance, VectorParams

    if not client.collection_exists(name):
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
