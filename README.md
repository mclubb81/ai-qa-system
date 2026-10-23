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
- **Retriever** (optional RAG) -- runs once before the Planner. When Qdrant/RAG is configured, it
  retrieves relevant indexed product docs for the Planner to ground test cases in; it degrades
  silently (returns no context) when RAG isn't configured.
- **Logging** (optional, Postgres) -- every node is wrapped to record its own duration and any
  escaping error; every LLM call is timed and sized. Writes are always best-effort -- a logging DB
  outage never crashes or blocks a live run.

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

## RAG (optional)

The Planner can be grounded in retrieved product docs, and Bug Triage can look up similar
previously-known bugs, via [Qdrant](https://qdrant.tech/) + Google's free `text-embedding-004`
embeddings. This is entirely optional -- leave the `.env` RAG fields blank and `qa-agent` runs
exactly as without it.

```bash
pip install -e ".[rag]"
```

1. Create a free [Qdrant Cloud](https://cloud.qdrant.io) cluster and grab its URL + API key.
2. In `.env`, set `QDRANT_URL`, `QDRANT_API_KEY`, and `GOOGLE_API_KEY` (same free key as the
   `google` LLM provider above -- get one at https://aistudio.google.com/apikey).
3. Seed the knowledge base:

```bash
qa-agent ingest-docs ./docs --chunk-size 1000 --chunk-overlap 100
qa-agent ingest-bugs ./known_bugs.json
```

`ingest-docs` indexes `.md`/`.txt` files (one file or a directory) into the `qa_docs` collection.
`ingest-bugs` indexes a JSON file -- a list of `{id?, title, description, severity?}` records --
into the `qa_bugs` collection.

## Logging + config (optional, Postgres)

Every run can log structured history -- run outcomes, per-node transitions with duration,
per-LLM-call timing/size, and errors with stack traces -- to Postgres, and settings can be
managed from a second Postgres database instead of only `.env`. Both are entirely optional --
leave the `.env` Postgres fields blank and `qa-agent` behaves exactly as without them.

```bash
pip install -e ".[db]"
docker compose up -d   # starts one local Postgres with both qa_logs and qa_config created
```

In `.env`, set `QA_LOGS_DATABASE_URL` and `QA_CONFIG_DATABASE_URL` (the `docker-compose.yml`
defaults match `.env.example`'s placeholders). Schema is created automatically on first use --
`qa-agent db-init` is available if you want to set it up explicitly instead.

```bash
qa-agent config set max_retries 3       # overrides MAX_RETRIES from .env once the config DB is reachable
qa-agent config get max_retries
qa-agent config list
```

Config keys must match a `Settings` field name (e.g. `llm_provider`, `max_retries`,
`playwright_headless`, `rag_docs_top_k`) to take effect -- values are stored as JSON, so
`qa-agent config set playwright_headless false` stores a real boolean, not the string `"false"`.

## Development

```bash
pytest                       # unit tests, mocked LLM/MCP -- no API key or Node needed
python scripts/check_mcp.py  # manual sanity check: launches Playwright MCP, lists real tools
ruff check src tests scripts
```

Tests marked `@pytest.mark.integration` spawn real subprocesses or call real APIs and are excluded
from the default `pytest` run; run them explicitly with `pytest -m integration` once you have an
API key and Node set up.
