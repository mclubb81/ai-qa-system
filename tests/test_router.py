from qa_agent.graph.router import route
from qa_agent.graph.state import Bug, QAState, StepResult, TestCase, TestCaseResult


def _base_state(**overrides) -> QAState:
    state: QAState = {
        "run_id": "test-run",
        "target_url": "https://example.com",
        "requirements_raw": "check the page loads",
        "llm_provider": "groq",
        "llm_model": "",
        "screenshot_dir": "/tmp/does-not-matter",
        "max_retries": 1,
        "retry_counts": {},
        "retrieved_docs": [],
        "test_plan": None,
        "test_results": [],
        "bugs": [],
        "errors": [],
        "started_at": "2026-01-01T00:00:00Z",
        "report_markdown_path": None,
        "report_json_path": None,
    }
    state.update(overrides)
    return state


def _test_case(id_: str = "TC-01") -> TestCase:
    return TestCase(id=id_, title="Check title", priority="high", steps=["Navigate", "Assert title"])


def _passed_step() -> StepResult:
    return StepResult(description="Navigate", status="pass")


def test_routes_to_retriever_when_docs_not_retrieved():
    state = _base_state(retrieved_docs=None, test_plan=None)
    assert route(state) == "retriever"


def test_routes_to_planner_when_no_plan():
    state = _base_state(retrieved_docs=[], test_plan=None)
    assert route(state) == "planner"


def test_routes_to_executor_when_test_case_pending():
    state = _base_state(test_plan=[_test_case()], test_results=[])
    assert route(state) == "executor"


def test_routes_to_analyzer_when_result_unanalyzed():
    tc = _test_case()
    result = TestCaseResult(
        test_case_id=tc.id,
        title=tc.title,
        priority=tc.priority,
        steps=[_passed_step()],
        started_at="2026-01-01T00:00:00Z",
        verdict=None,
    )
    state = _base_state(test_plan=[tc], test_results=[result])
    assert route(state) == "analyzer"


def test_routes_to_triage_when_bug_flagged_and_untriaged():
    tc = _test_case()
    result = TestCaseResult(
        test_case_id=tc.id,
        title=tc.title,
        priority=tc.priority,
        steps=[_passed_step()],
        started_at="2026-01-01T00:00:00Z",
        verdict="fail",
        suspected_bug=True,
    )
    state = _base_state(test_plan=[tc], test_results=[result], bugs=[])
    assert route(state) == "triage"


def test_routes_to_report_when_everything_resolved():
    tc = _test_case()
    result = TestCaseResult(
        test_case_id=tc.id,
        title=tc.title,
        priority=tc.priority,
        steps=[_passed_step()],
        started_at="2026-01-01T00:00:00Z",
        verdict="fail",
        suspected_bug=True,
    )
    bug = Bug(
        id="BUG-01",
        title="Something broke",
        severity="high",
        related_test_case_id=tc.id,
        repro_steps=["Navigate"],
        expected="x",
        actual="y",
        suspected_root_cause="z",
    )
    state = _base_state(test_plan=[tc], test_results=[result], bugs=[bug])
    assert route(state) == "report"


def test_routes_to_report_when_all_pass_no_bugs():
    tc = _test_case()
    result = TestCaseResult(
        test_case_id=tc.id,
        title=tc.title,
        priority=tc.priority,
        steps=[_passed_step()],
        started_at="2026-01-01T00:00:00Z",
        verdict="pass",
        suspected_bug=False,
    )
    state = _base_state(test_plan=[tc], test_results=[result], bugs=[])
    assert route(state) == "report"
