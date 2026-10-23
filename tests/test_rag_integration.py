import os

import pytest

from qa_agent.config import get_settings
from qa_agent.rag.collections import ensure_collection
from qa_agent.rag.service import RagService

pytestmark = pytest.mark.integration

REQUIRED_ENV = ("QDRANT_URL", "QDRANT_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def real_rag_service():
    if any(not os.environ.get(var) for var in REQUIRED_ENV):
        pytest.skip(f"Set {', '.join(REQUIRED_ENV)} to run RAG integration tests.")
    get_settings.cache_clear()
    return RagService.from_settings()


async def test_round_trip_doc_ingest_and_retrieve(real_rag_service):
    from qa_agent.rag.client import get_qdrant_client

    settings = get_settings()
    ensure_collection(get_qdrant_client(settings), settings.qdrant_docs_collection)

    real_rag_service.upsert_docs([("The sign-up form requires an 8-character password.", "integration-test")])
    docs = await real_rag_service.retrieve_docs("What are the password requirements for sign-up?")

    assert any("password" in doc.text.lower() for doc in docs)
