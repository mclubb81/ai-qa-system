from qa_agent.graph.state import NodeName, QAState


def route(state: QAState) -> NodeName:
    """The Coordinator: a pure, deterministic function of state.

    Decides which agent runs next based purely on the shapes of
    retrieved_docs / test_plan / test_results / bugs -- there is no
    separate "status" field to keep in sync. This is wired in as the
    conditional-edge function from every worker node, and as the
    conditional entry point. retrieved_docs is checked first and only
    ever `None` once, at the very start of a run.
    """
    if state["retrieved_docs"] is None:
        return "retriever"

    if state["test_plan"] is None:
        return "planner"

    executed_ids = {r.test_case_id for r in state["test_results"]}
    pending = [tc for tc in state["test_plan"] if tc.id not in executed_ids]
    if pending:
        return "executor"

    unanalyzed = [r for r in state["test_results"] if r.verdict is None]
    if unanalyzed:
        return "analyzer"

    triaged_ids = {b.related_test_case_id for b in state["bugs"]}
    flagged = [
        r
        for r in state["test_results"]
        if r.suspected_bug and r.test_case_id not in triaged_ids
    ]
    if flagged:
        return "triage"

    if state["generate_regression_scripts"]:
        codegen_ids = {g.test_case_id for g in state["generated_scripts"]}
        pending_codegen = [
            r
            for r in state["test_results"]
            if r.verdict == "pass" and r.test_case_id not in codegen_ids
        ]
        if pending_codegen:
            return "codegen"

    return "report"
