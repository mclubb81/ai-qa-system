from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from qa_agent.rag.models import RetrievedDoc


class TestCase(BaseModel):
    id: str
    title: str
    priority: Literal["high", "medium", "low"]
    steps: list[str]


class StepResult(BaseModel):
    description: str
    status: Literal["pass", "fail"]
    tool_calls: list[dict] = Field(default_factory=list)
    error: str | None = None
    screenshot_path: str | None = None


class TestCaseResult(BaseModel):
    test_case_id: str
    title: str
    priority: str
    steps: list[StepResult] = Field(default_factory=list)
    verdict: Literal["pass", "fail", "flaky"] | None = None
    reasoning: str | None = None
    suspected_bug: bool = False
    started_at: str
    finished_at: str | None = None


class Bug(BaseModel):
    id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    related_test_case_id: str
    repro_steps: list[str]
    expected: str
    actual: str
    suspected_root_cause: str
    screenshot_refs: list[str] = Field(default_factory=list)
    similar_bug_refs: list[str] = Field(default_factory=list)
    repro_script_path: str | None = None


class GeneratedScript(BaseModel):
    """A standalone Playwright regression script for a passing test case,
    written by the codegen node (and later re-validated/re-synthesized by
    Healer, which reads sidecar_path independent of any particular run)."""

    test_case_id: str
    title: str
    script_path: str
    sidecar_path: str


class QAState(TypedDict):
    run_id: str
    target_url: str
    requirements_raw: str

    llm_provider: str
    llm_model: str

    screenshot_dir: str
    max_retries: int
    retry_counts: dict[str, int]

    retrieved_docs: list[RetrievedDoc] | None
    test_plan: list[TestCase] | None
    test_results: list[TestCaseResult]
    bugs: list[Bug]
    errors: list[str]

    generated_scripts: list[GeneratedScript]
    generate_regression_scripts: bool

    started_at: str
    report_markdown_path: str | None
    report_json_path: str | None


NodeName = Literal[
    "retriever", "planner", "executor", "analyzer", "triage", "codegen", "report"
]
