# Logging + Config (Postgres)

[← back to README](../README.md)

Structured, relational run history (Postgres) plus externalized JSON settings management
(a second Postgres database), both **entirely optional** -- leave the `.env` Postgres fields
blank and `qa-agent` behaves exactly as without either.

## Why two separate databases

- **`qa_logs`** -- append-only telemetry: run outcomes, per-node transitions, per-LLM-call
  timing/size, errors. Write-heavy, never mutated after the fact (except `runs`, which gets one
  `UPDATE` at run end).
- **`qa_config`** -- a small, occasionally-mutated key-value settings store.

Splitting them into two databases (rather than two tables or two schemas in one database) keeps
the failure domains separable: a logging outage can never block a config read, and vice versa, and
an operator can stand up only the one they need. Both run on one local Postgres server via
`docker-compose.yml` for convenience -- see [Local setup](#local-setup).

**The one bootstrapping exception**: `QA_LOGS_DATABASE_URL` and `QA_CONFIG_DATABASE_URL` themselves
can never live *in* the config DB, since you need them to find it. They're always read from `.env`
(`config.py`'s bootstrap `Settings`), never overlaid.

## `qa_logs` schema

```sql
CREATE TABLE runs (
    run_id               TEXT PRIMARY KEY,
    target_url           TEXT NOT NULL,
    requirements_summary TEXT,
    llm_provider         TEXT,
    llm_model            TEXT,
    started_at           TIMESTAMPTZ NOT NULL,
    finished_at          TIMESTAMPTZ,
    overall_status       TEXT,
    bug_count            INTEGER,
    test_case_count      INTEGER,
    error                TEXT
);

CREATE TABLE node_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    node_name   TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    ok          BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE llm_calls (
    id             BIGSERIAL PRIMARY KEY,
    run_id         TEXT NOT NULL,
    node_name      TEXT NOT NULL,
    provider       TEXT,
    model          TEXT,
    started_at     TIMESTAMPTZ NOT NULL,
    finished_at    TIMESTAMPTZ NOT NULL,
    duration_ms    DOUBLE PRECISION NOT NULL,
    prompt_chars   INTEGER,
    response_chars INTEGER,
    ok             BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE errors (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT,
    node_name   TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    message     TEXT NOT NULL,
    stack_trace TEXT
);
```

(`node_events`/`llm_calls` are indexed on `run_id`; `errors` too.)

**Deliberately no foreign keys** from `node_events`/`llm_calls`/`errors` back to `runs.run_id`.
A FK violation would be a second failure mode stacked on top of the try/except every `LogService`
write already swallows, for no real integrity benefit in what's an append-only telemetry store --
not an OLTP system. Any dashboard or query against these tables should `LEFT JOIN` and tolerate
orphan rows (e.g. a `node_events` row logged before its `runs` row has landed, under a transient
connectivity blip).

## `qa_config` schema

```sql
CREATE TABLE qa_config (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Values are stored as real JSON types, not strings -- the CLI's `_coerce_value` helper tries
`json.loads(value)` first and only falls back to the raw string if that fails. So
`qa-agent config set playwright_headless false` stores the JSON boolean `false`, and
`qa-agent config set max_retries 3` stores the JSON number `3`.

## `ConfigService` contract

```python
class ConfigService:
    enabled: bool  # connection is not None

    @classmethod
    def from_settings(cls, settings=None) -> "ConfigService": ...  # opens a sync connection,
                                                                     # ensures schema automatically

    def get(self, key: str, default=None): ...   # never raises -- returns `default` on any failure
    def get_all(self) -> dict: ...                # never raises -- returns {} on any failure
    def set(self, key: str, value) -> None: ...   # raises RuntimeError when disabled
```

Same dependency-injection pattern as `RagService` in [docs/rag.md](rag.md): `enabled` is the single
source of truth, reads degrade gracefully, writes (an explicit `qa-agent config set`) raise when
there's nothing to write to. Uses a plain **sync** `psycopg.Connection` -- config is read once at
settings-resolution time, often from a synchronous CLI command, so there's no event loop to require
async here.

## `LogService` contract -- the one asymmetric case

```python
class LogService:
    enabled: bool  # pool is not None

    @classmethod
    def from_settings(cls, settings=None) -> "LogService": ...

    async def log_run_start(...) -> None: ...
    async def log_run_end(...) -> None: ...
    async def log_node_transition(...) -> None: ...
    async def log_llm_call(...) -> None: ...
    async def log_error(...) -> None: ...
```

Unlike `RagService`/`ConfigService`, **every** `LogService` method -- including all five writes
above -- swallows its own exceptions. There is no "raises when disabled" case here at all, because
every one of these calls happens *mid-run*, inside LangGraph node execution, and a logging failure
must never crash or stall a live QA session.

- `_ensure_ready()` opens the connection pool and ensures the schema **exactly once** per
  `LogService` instance (i.e. once per run). On failure, it permanently disables itself
  (`self._pool = None`) rather than retrying on every subsequent log call -- so a dead logging DB
  costs one failed connection attempt per run, not one per node/LLM call.
- Uses an **async** `psycopg_pool.AsyncConnectionPool`, built with `open=False` so construction
  itself performs no I/O (opening happens lazily, inside `_ensure_ready`, since that requires
  `await`).
- If the pool opens fine but a later write fails (e.g. a transient network blip mid-run), that
  one write is swallowed and logged as a warning -- the pool stays live and the *next* write is
  still attempted (no permanent disable on a transient per-write failure, only on the initial
  open/schema-ensure failure).

## How the graph is instrumented

- **`graph/build.py::_with_node_logging`** wraps every node before `graph.add_node(...)`. It times
  the node, calls `log_node_transition` on both success and failure, and on failure also calls
  `log_error` -- **then re-raises**. This is the one error-logging boundary in the whole pipeline
  that does *not* swallow: a real failure still propagates to the CLI, which exits non-zero. See
  [docs/architecture.md](architecture.md) for the full node wiring.
- **`llm_logging.py::logged_llm_call`** wraps the single LLM call inside each of
  planner/analyzer/triage/executor, logging duration and prompt/response size via `log_llm_call`.
  Known limitation: the executor's ReAct agent may issue multiple internal LLM turns per
  `ainvoke()` call, but this only produces one aggregate `llm_calls` row per test case, not one per
  internal turn.

## Config precedence chain

`config.py::get_effective_settings(settings=None)` overlays `qa_config` DB values onto the `.env`
bootstrap `Settings` via `base.model_copy(update=overrides)`. It's deliberately **uncached**
(unlike `get_settings()`, which is `@lru_cache`'d) so a `qa-agent config set` takes effect on the
very next call, not frozen behind a stale singleton.

Full precedence, highest wins: **CLI flag (if explicitly passed) → `qa_config` DB (if reachable) →
`.env`/hardcoded default**. For example, `qa-agent run`'s `--headless`/`--max-retries`/
`--reports-dir` flags default to `None` in `cli.py` and are only resolved against
`get_effective_settings()` when the user didn't pass them explicitly -- see `cli.py`'s `run`
command for the exact resolution logic.

Only keys that match an existing `Settings` field name take effect (e.g. `llm_provider`,
`max_retries`, `playwright_headless`, `rag_docs_top_k`) -- `model_copy(update=...)` will still
accept an unrecognized key without error, but it won't influence any field lookup elsewhere.

## Local setup

```bash
pip install -e ".[db]"
docker compose up -d
```

`docker-compose.yml` runs one `postgres:16-alpine` container. The official image auto-creates
`qa_logs` (via `POSTGRES_DB`); `docker/init-db.sh` additionally creates `qa_config` the first time
the container starts against a fresh (empty) data volume.

In `.env`, set `QA_LOGS_DATABASE_URL` and `QA_CONFIG_DATABASE_URL` (defaults in `.env.example`
match the compose file's credentials). Schema is created automatically on first connect by both
`ConfigService.from_settings()` and `LogService._ensure_ready()` -- `qa-agent db-init` exists for
explicitly (re-)creating both schemas up front, decoupled from a first `run`/`config set`, which is
useful for CI/ops setup.

## CLI reference (brief)

```bash
qa-agent config set max_retries 3
qa-agent config get max_retries
qa-agent config list
qa-agent db-init
```

Full flag tables and exit codes: [docs/cli.md](cli.md).

## Test coverage

- `tests/test_config_service.py`, `tests/test_log_service.py` -- hand-rolled stubs
  (`_StubCursor`, `_StubSyncConnection`, `_StubAsyncPool`) shared via `tests/conftest.py`, following
  the repo's no-mocking-framework convention.
- `tests/test_db_integration.py` -- `@pytest.mark.integration`, a real round-trip against live
  Postgres (e.g. the `docker compose` instance); skipped by default.
- `tests/test_cli_config.py` -- the `config set/get/list` commands against a stub `ConfigService`.
- `tests/test_ids.py` -- regression test for `run_id` uniqueness (see below).

## Why `run_id` has a random suffix

`utils/ids.py::new_run_id()` returns `f"{timestamp}-{uuid4().hex[:8]}"`, not a bare timestamp. Now
that `run_id` is a Postgres primary/foreign key in a persistent `runs` table, a bare
`%Y%m%dT%H%M%SZ` timestamp could collide under concurrent or rapid-succession runs within the same
second; the random suffix makes it safe as a database key while keeping the sortable timestamp
prefix for readability.
