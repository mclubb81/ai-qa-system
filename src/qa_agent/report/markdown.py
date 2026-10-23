from jinja2 import Template

from qa_agent.report.models import QAReport

_TEMPLATE = Template(
    """\
# QA Report: {{ report.run_id }}

- **Target URL:** {{ report.target_url }}
- **Requirements:** {{ report.requirements_summary }}
- **Started:** {{ report.started_at }}
- **Finished:** {{ report.finished_at }}
- **Overall status:** {{ report.overall_status | upper }}

## Test Case Results

| Test Case | Priority | Verdict | Notes |
|---|---|---|---|
{% for result in report.test_results -%}
| {{ result.test_case_id }}: {{ result.title }} | {{ result.priority }} | {{ result.verdict or "pending" }} | {{ (result.reasoning or "")[:120] }} |
{% endfor %}

{% for result in report.test_results %}
### {{ result.test_case_id }}: {{ result.title }}

- Priority: {{ result.priority }}
- Verdict: **{{ result.verdict or "pending" }}**
{% if result.reasoning %}- Reasoning: {{ result.reasoning }}{% endif %}

| # | Step | Status | Error | Screenshot |
|---|---|---|---|---|
{% for step in result.steps -%}
| {{ loop.index }} | {{ step.description }} | {{ step.status }} | {{ step.error or "" }} | {% if step.screenshot_path %}![screenshot]({{ step.screenshot_path }}){% endif %} |
{% endfor %}
{% endfor %}

## Bugs

{% if not report.bugs %}
No bugs were flagged during this run.
{% endif %}
{% for bug in report.bugs %}
### {{ bug.id }}: {{ bug.title }}

- Severity: **{{ bug.severity }}**
- Related test case: {{ bug.related_test_case_id }}

**Repro steps:**
{% for step in bug.repro_steps %}
{{ loop.index }}. {{ step }}
{% endfor %}

- **Expected:** {{ bug.expected }}
- **Actual:** {{ bug.actual }}
- **Suspected root cause:** {{ bug.suspected_root_cause }}

{% for ref in bug.screenshot_refs %}
![screenshot]({{ ref }})
{% endfor %}
{% endfor %}
"""
)


def render_markdown(report: QAReport) -> str:
    return _TEMPLATE.render(report=report)
