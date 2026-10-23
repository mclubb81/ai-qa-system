from qa_agent.agents.retriever import make_retriever_node
from qa_agent.rag.models import RetrievedDoc


class _StubRagService:
    def __init__(self, docs):
        self._docs = docs

    async def retrieve_docs(self, query, top_k=None):
        return self._docs


async def test_retriever_node_returns_docs_from_service():
    docs = [RetrievedDoc(text="Some doc", source="sample.md", score=0.9)]
    node = make_retriever_node(_StubRagService(docs))

    state = {"target_url": "https://example.com", "requirements_raw": "Check sign-up works"}
    update = await node(state)

    assert update["retrieved_docs"] == docs


async def test_retriever_node_returns_empty_list_when_service_finds_nothing():
    node = make_retriever_node(_StubRagService([]))

    state = {"target_url": "https://example.com", "requirements_raw": "Check sign-up works"}
    update = await node(state)

    assert update["retrieved_docs"] == []
