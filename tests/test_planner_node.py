from qa_agent.agents.planner import TestPlanResponse, make_planner_node
from qa_agent.graph.state import TestCase


class _StubStructuredLLM:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _StubLLM:
    def __init__(self, response):
        self._response = response

    def with_structured_output(self, schema):
        return _StubStructuredLLM(self._response)


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
