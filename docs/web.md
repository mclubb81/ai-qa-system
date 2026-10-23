# Web UI

[← back to README](../README.md)

A local, dark-themed Flask UI (`src/qa_agent/web/`) over the same library entrypoints the CLI
uses -- `run_qa_session()`, `heal_many()`/`heal_script()`, and `ConfigService`. It's a thin
browser-based alternative to `qa-agent run`/`heal`/`config`, not a separate system: every run it
starts writes the exact same `reports/<run-id>/report.md`/`report.json` the CLI produces.

## Install & launch

```bash
pip install -e ".[web]"
qa-agent web
```

| Flag | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Interface to bind. Loopback-only by default -- this is a local, single-operator tool with no auth, same trust model as the CLI itself. |
| `--port` | `5000` | Port to listen on. |
| `--debug` | off | Enable Flask debug mode (reload + interactive debugger). Refused unless `--host` is loopback, since Werkzeug's debugger allows arbitrary code execution if it's reachable. |

Open `http://127.0.0.1:5000`.

## Pages

- **New Run** (`/runs/new`) -- same inputs as `qa-agent run` (target URL, requirements text or
  file upload, provider/model override, headless toggle, max retries,
  generate-regression-scripts toggle). Submitting starts the run in a background thread and
  redirects to a status page that polls until it finishes, then links to the report.
- **Reports** (`/reports`) -- every run found under `reports_dir`, newest first. Click through to
  a detail page: test cases (expandable, with step-by-step results and screenshots), bugs
  (severity-coded, with repro steps), and any generated regression scripts.
- **Healer** (`/healer`) -- every generated regression script found under
  `reports_dir/*/generated_tests/*.py`. Select one or more, optionally override the
  provider/model, and heal them the same way `qa-agent heal` does -- results (`healed` /
  `still_valid` / `regression_detected`) show on the same polling status page as a run.
- **Config** (`/config`) -- view effective settings and edit `qa_config` DB overrides, mirroring
  `qa-agent config set/get/list`. Shows a read-only banner instead of a crash when
  `QA_CONFIG_DATABASE_URL` isn't set. API keys are masked (`•••• set`) and never round-tripped
  into the page -- only a non-empty, non-masked submission overwrites one; a "clear" checkbox
  next to each key removes its override. Dict-typed settings (`provider_limits`,
  `node_candidate_providers`, etc.) are edited as raw JSON; invalid JSON is flagged and that one
  field is skipped, not the whole save.

## How long-running work is handled

`run_qa_session`/`heal_script` are async and can take minutes (a real Playwright browser session
plus several LLM calls); Flask itself is sync. Each "start a run"/"heal" submission creates an
in-memory `Job`, spawns a daemon thread that does `asyncio.run(...)`, and immediately redirects to
a status page (`/jobs/<id>`) that polls `/api/jobs/<id>` every ~2s via a small vanilla-JS script
until the job is `done`/`error`. No new infra (no Redis/Celery) -- this matches the project's
existing preference for minimal moving parts.

Job state lives only in that one process's memory and is lost on restart; this is an accepted
tradeoff, not a gap, since the durable artifact of a run (`report.json`) is already written to
disk by `run_qa_session` independent of the job registry.

## Security notes

Not hardened for multi-user or internet-facing use -- same trust model as running `qa-agent run`
from a terminal, so there's no login/CSRF. What *is* handled: screenshots are served via Flask's
`send_from_directory` (rejects path traversal), and a healer selection is independently
re-validated against `reports_dir` before being passed to `heal_script` -- a tampered/out-of-tree
path is rejected with `400`.
