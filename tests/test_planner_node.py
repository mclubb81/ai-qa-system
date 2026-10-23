from qa_agent.agents.planner import TestPlanResponse, make_planner_node
from qa_agent.graph.state import TestCase
from qa_agent.rag.models import RetrievedDoc


class _StubStructuredLLM:
    def __init__(self, response):
        self._response = response
        self.last_messages = None

    async def ainvoke(self, messages):
        self.last_messages = messages
        return self._response


class _StubLLM:
    def __init__(self, response):
        self._response = response
        self.structured_llm = None

    def with_structured_output(self, schema):
        self.structured_llm = _StubStructuredLLM(self._response)
        return self.structured_llm


async def test_planner_node_sets_test_plan():
    canned = TestPlanResponse(
        test_cases=[
            TestCase(id="TC-01", title="Page loads", priority="high", steps=["Navigate to the URL"]),
        ]
    )
    node = make_planner_node(_StubLLM(canned))

    state = {
        "target_url": "https://example.com",
        "requirements_raw": "Check the page loads",
    }
    update = await node(state)

    assert update["test_plan"] == canned.test_cases
    assert update["test_plan"][0].id == "TC-01"


async def test_planner_node_includes_retrieved_docs_in_prompt():
    canned = TestPlanResponse(test_cases=[])
    stub_llm = _StubLLM(canned)
    node = make_planner_node(stub_llm)

    state = {
        "target_url": "https://example.com",
        "requirements_raw": "Check sign-up works",
        "retrieved_docs": [RetrievedDoc(text="Sign-up requires an 8+ char password.", source="sample.md", score=0.9)],
    }
    await node(state)

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "Sign-up requires an 8+ char password." in user_message
    assert "sample.md" in user_message


async def test_planner_node_omits_docs_block_when_no_docs_retrieved():
    canned = TestPlanResponse(test_cases=[])
    stub_llm = _StubLLM(canned)
    node = make_planner_node(stub_llm)

    state = {
        "target_url": "https://example.com",
        "requirements_raw": "Check sign-up works",
        "retrieved_docs": [],
    }
    await node(state)

    user_message = stub_llm.structured_llm.last_messages[1].content
    assert "retrieved" not in user_message.lower()
