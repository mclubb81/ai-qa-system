# qa-agent

An AI-powered, multi-agent QA automation system built with [LangGraph](https://github.com/langchain-ai/langgraph)
and the official [Playwright MCP](https://playwright.dev/mcp/introduction) server.

Point it at a URL and a set of requirements, and a Coordinator agent routes work through a
Planner → Executor → Analyzer → Bug Triage loop until everything is resolved, then writes a
Markdown + JSON report.

## Architecture

- **Coordinator** (`graph/router.py`) -- a pure, deterministic router function. It decides the
  next agent purely from the shape of the current state (no plan yet → Planner; a test case not
  yet run → Executor; a result not yet judged → Analyzer; a flagged bug not yet triaged → Triage;
  otherwise → write the report).
- **Planner** -- turns the target URL + requirements into a structured list of test cases.
- **Executor** -- the only agent with tools bound to it. Drives a real, persistent browser session
  via Playwright MCP tools (navigate, snapshot, click, type, screenshot, ...) to run one test
  case's steps at a time.
- **Analyzer** -- judges each executed test case pass/fail/flaky, with a deterministic
  threshold-based retry for "flaky" verdicts.
- **Bug Triage** -- turns suspected-bug results into structured, GitHub-issue-ready bug reports.

The core orchestration lives behind a single library entrypoint, `run_qa_session(...)`
(`core/session.py`), so the CLI is a thin wrapper and a future API/UI layer can call it directly.

## Setup

Requires Python 3.11+ and Node.js (Playwright MCP runs via `npx`).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
npx -y playwright install chromium

cp .env.example .env
# edit .env and add a free API key for your chosen provider (see below)
```

## LLM provider

Provider-agnostic by design -- swap providers via `LLM_PROVIDER` in `.env` or `--provider` on the
CLI. Defaults to **Groq**, which has a generous free API tier with good tool-calling support.

| Provider | Free tier? | Install extra | Get a key |
|---|---|---|---|
| `groq` (default) | Yes | included by default | https://console.groq.com/keys |
| `google` | Yes | `pip install -e ".[google]"` | https://aistudio.google.com/apikey |
| `anthropic` | No | `pip install -e ".[anthropic]"` | https://console.anthropic.com |
| `openai` | No | `pip install -e ".[openai]"` | https://platform.openai.com |

## Usage

```bash
qa-agent run --url https://example.com --requirements "Check the page loads and has a title"

qa-agent run --url https://myapp.com --requirements ./examples/requirements_example.md \
  --provider google --model gemini-2.5-flash
```

Each run writes `reports/<run-id>/report.md`, `report.json`, and any captured screenshots under
`reports/<run-id>/screenshots/`.

## Development

```bash
pytest                       # unit tests, mocked LLM/MCP -- no API key or Node needed
python scripts/check_mcp.py  # manual sanity check: launches Playwright MCP, lists real tools
ruff check src tests scripts
```

Tests marked `@pytest.mark.integration` spawn real subprocesses or call real APIs and are excluded
from the default `pytest` run; run them explicitly with `pytest -m integration` once you have an
API key and Node set up.
