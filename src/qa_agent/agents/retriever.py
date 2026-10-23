from collections.abc import Awaitable, Callable

from qa_agent.graph.state import QAState
from qa_agent.rag.service import RagService


def make_retriever_node(rag_service: RagService) -> Callable[[QAState], Awaitable[dict]]:
    async def retriever_node(state: QAState) -> dict:
        query = f"{state['target_url']}\n\n{state['requirements_raw']}"
        docs = await rag_service.retrieve_docs(query)
        return {"retrieved_docs": docs}

    return retriever_node
