from pydantic import BaseModel, Field

from qa_agent.graph.state import Bug, GeneratedScript, TestCaseResult


class QAReport(BaseModel):
    """The report's content model -- this *is* the machine-readable JSON schema."""

    run_id: str
    target_url: str
    requirements_summary: str
    started_at: str
    finished_at: str
    overall_status: str
    test_results: list[TestCaseResult] = Field(default_factory=list)
    bugs: list[Bug] = Field(default_factory=list)
    generated_scripts: list[GeneratedScript] = Field(default_factory=list)
