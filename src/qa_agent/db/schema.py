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


async def ensure_logs_schema(pool: "AsyncConnectionPool") -> None:
    async with pool.connection() as conn:
        await conn.execute(_LOGS_DDL)
