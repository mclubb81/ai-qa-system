import pytest

from qa_agent.config import Settings
from qa_agent.rag.service import RagService


class _StubPoint:
    def __init__(self, payload, score, id="x"):
        self.payload = payload
        self.score = score
        self.id = id


class _StubQueryResponse:
    def __init__(self, points):
        self.points = points


class _StubQdrantClient:
    def __init__(self, canned_points=None, fail=False):
        self._canned_points = canned_points or []
        self.fail = fail
        self.upserted = []

    def query_points(self, collection_name, query, limit, with_payload=True):
        if self.fail:
            raise RuntimeError("boom")
        return _StubQueryResponse(self._canned_points[:limit])

    def upsert(self, collection_name, points):
        self.upserted.append((collection_name, points))


class _StubEmbeddings:
    def __init__(self, vector=None):
        self._vector = vector or [0.1, 0.2, 0.3]

    async def aembed_query(self, text):
        return self._vector

    def embed_documents(self, texts):
        return [self._vector for _ in texts]


def _settings() -> Settings:
    return Settings()


async def test_retrieve_docs_returns_canned_results():
    points = [_StubPoint(payload={"text": "Some doc text", "source": "sample.md"}, score=0.9)]
    service = RagService(_StubQdrantClient(canned_points=points), _StubEmbeddings(), _settings())

    docs = await service.retrieve_docs("some query")

    assert len(docs) == 1
    assert docs[0].text == "Some doc text"
    assert docs[0].source == "sample.md"
    assert docs[0].score == 0.9


async def test_find_similar_bugs_returns_canned_results():
    points = [
        _StubPoint(
            payload={"id": "BUG-SEED-001", "title": "Banner missing", "description": "...", "severity": "medium"},
            score=0.8,
        )
    ]
    service = RagService(_StubQdrantClient(canned_points=points), _StubEmbeddings(), _settings())

    bugs = await service.find_similar_bugs("banner never shows")

    assert len(bugs) == 1
    assert bugs[0].id == "BUG-SEED-001"
    assert bugs[0].title == "Banner missing"


async def test_retrieve_docs_returns_empty_when_disabled():
    service = RagService(None, None, _settings())
    assert await service.retrieve_docs("query") == []


async def test_find_similar_bugs_returns_empty_when_disabled():
    service = RagService(None, None, _settings())
    assert await service.find_similar_bugs("query") == []


async def test_retrieve_docs_returns_empty_on_client_error():
    service = RagService(_StubQdrantClient(fail=True), _StubEmbeddings(), _settings())
    assert await service.retrieve_docs("query") == []


async def test_upsert_docs_writes_through_and_returns_count():
    client = _StubQdrantClient()
    service = RagService(client, _StubEmbeddings(), _settings())

    count = service.upsert_docs([("chunk one", "a.md"), ("chunk two", "b.md")])

    assert count == 2
    assert len(client.upserted) == 1
    collection_name, points = client.upserted[0]
    assert collection_name == "qa_docs"
    assert len(points) == 2


async def test_upsert_bugs_writes_through_and_returns_count():
    client = _StubQdrantClient()
    service = RagService(client, _StubEmbeddings(), _settings())

    count = service.upsert_bugs([{"title": "Bug one", "description": "desc", "severity": "low"}])

    assert count == 1
    collection_name, points = client.upserted[0]
    assert collection_name == "qa_bugs"
    assert points[0].payload["id"] == "BUG-SEED-000"


def test_upsert_docs_raises_when_disabled():
    service = RagService(None, None, _settings())
    with pytest.raises(RuntimeError):
        service.upsert_docs([("chunk", "a.md")])


def test_upsert_bugs_raises_when_disabled():
    service = RagService(None, None, _settings())
    with pytest.raises(RuntimeError):
        service.upsert_bugs([{"title": "x", "description": "y"}])
