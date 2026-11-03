from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg
    from psycopg_pool import AsyncConnectionPool

_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS qa_config (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Lives in the qa_config database (not a third database) so a future
# narrowly-scoped Postgres role for an external program (e.g. a remote
# reinforcement-learning loop) can be granted access to just this table --
# Postgres grants are per-table, and qa_config's own key/value rows may hold
# provider API keys that such a role should never see.
#
# No FK from llm_calls/runs (schema below) to this table, for the same
# reason node_events/llm_calls/errors have no FK to runs: this is
# attribution metadata on an append-only telemetry store, not a
# referential-integrity-critical relationship, and an external writer's
# node_name may transiently not match until reconciled.
_PROMPTS_DDL = """
CREATE TABLE IF NOT EXISTS prompt_versions (
    id          BIGSERIAL PRIMARY KEY,
    node_name   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    created_by  TEXT,
    metadata    JSONB,
    is_active   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_name, version)
);
-- Enforces "at most one active version per node" without a second table.
CREATE UNIQUE INDEX IF NOT EXISTS prompt_versions_one_active_idx
    ON prompt_versions(node_name) WHERE is_active;
CREATE INDEX IF NOT EXISTS prompt_versions_node_name_idx ON prompt_versions(node_name);
"""

# run_id columns below are plain indexed TEXT, not foreign keys to runs(run_id)
# -- a FK violation would be a second failure mode on top of the try/except
# every LogService write already swallows, for no real integrity benefit in
# an append-only telemetry store. Dashboards/queries should LEFT JOIN and
# tolerate orphan rows (e.g. a node_event logged before log_run_start lands).
_LOGS_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id               TEXT PRIMARY KEY,
    target_url            TEXT NOT NULL,
    requirements_summary  TEXT,
    llm_provider          TEXT,
    llm_model             TEXT,
    started_at            TIMESTAMPTZ NOT NULL,
    finished_at           TIMESTAMPTZ,
    overall_status        TEXT,
    bug_count             INTEGER,
    test_case_count       INTEGER,
    error                 TEXT
);
-- Added after the table above may already exist in a deployed DB, hence
-- ADD COLUMN IF NOT EXISTS rather than relying on CREATE TABLE IF NOT
-- EXISTS to pick it up. {node_name: version} snapshot of every prompted
-- node's active version at the start of this run -- lets an external
-- consumer (e.g. a remote RL loop) join run outcomes to the prompt
-- versions that produced them without re-deriving it from llm_calls.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS prompt_versions JSONB;

CREATE TABLE IF NOT EXISTS node_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL,
    node_name   TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    ok          BOOLEAN NOT NULL DEFAULT true
);
CREATE INDEX IF NOT EXISTS node_events_run_id_idx ON node_events(run_id);

CREATE TABLE IF NOT EXISTS llm_calls (
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
CREATE INDEX IF NOT EXISTS llm_calls_run_id_idx ON llm_calls(run_id);
-- See the ADD COLUMN note on runs.prompt_versions above. prompt_source_node
-- exists because Healer logs llm_calls under node_name="healer" but
-- actually reuses the executor's or codegen's prompt version numbering --
-- without it, a consumer can't tell which node's version-space a healer
-- row's prompt_version integer belongs to.
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS prompt_version INTEGER;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS prompt_source_node TEXT;

CREATE TABLE IF NOT EXISTS errors (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT,
    node_name   TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    message     TEXT NOT NULL,
    stack_trace TEXT
);
CREATE INDEX IF NOT EXISTS errors_run_id_idx ON errors(run_id);
"""


def ensure_config_schema(conn: "psycopg.Connection") -> None:
    with conn.cursor() as cur:
        cur.execute(_CONFIG_DDL)
    conn.commit()


def ensure_prompts_schema(conn: "psycopg.Connection") -> None:
    with conn.cursor() as cur:
        cur.execute(_PROMPTS_DDL)
    conn.commit()


async def ensure_logs_schema(pool: "AsyncConnectionPool") -> None:
    async with pool.connection() as conn:
        await conn.execute(_LOGS_DDL)
