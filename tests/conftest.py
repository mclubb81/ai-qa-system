"""Shared hand-rolled stubs for the Postgres-backed services (ConfigService,
PromptService, LogService). Follows the repo's existing no-mocking-framework
convention (see _StubQdrantClient/_StubEmbeddings in test_rag_service.py) --
promoted here since multiple services would otherwise duplicate
near-identical stub-connection boilerplate."""


class _StubCursor:
    """Stands in for a psycopg cursor. Recognizes the handful of SQL shapes
    ConfigService/PromptService actually issue rather than parsing
    arbitrary SQL."""

    def __init__(self, store: dict, fail: bool, prompt_rows: dict | None = None):
        self._store = store
        self._fail = fail
        self._prompt_rows = prompt_rows if prompt_rows is not None else {}
        self._result = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        if self._fail:
            raise RuntimeError("stub cursor failure")
        params = params or ()
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT value FROM qa_config WHERE"):
            (key,) = params
            self._result = ("one", self._store.get(key))
        elif normalized.startswith("SELECT key, value FROM qa_config"):
            self._result = ("all", list(self._store.items()))
        elif normalized.startswith("INSERT INTO qa_config"):
            key, value = params[0], params[1]
            self._store[key] = value.obj if hasattr(value, "obj") else value
            self._result = None
        elif normalized.startswith("CREATE TABLE IF NOT EXISTS qa_config"):
            self._result = None
        elif normalized.startswith("CREATE TABLE IF NOT EXISTS prompt_versions"):
            self._result = None
        elif normalized.startswith("SELECT content, version FROM prompt_versions WHERE"):
            (node_name,) = params
            rows = self._prompt_rows.get(node_name, [])
            active = next((r for r in rows if r["is_active"]), None)
            self._result = ("one_row", (active["content"], active["version"]) if active else None)
        elif normalized.startswith(
            "SELECT node_name, version, content, source, created_by, metadata, "
            "is_active, created_at FROM prompt_versions"
        ):
            (node_name,) = params
            rows = sorted(self._prompt_rows.get(node_name, []), key=lambda r: r["version"])
            self._result = (
                "all",
                [
                    (
                        node_name, r["version"], r["content"], r["source"], r["created_by"],
                        r["metadata"], r["is_active"], r["created_at"],
                    )
                    for r in rows
                ],
            )
        elif normalized == "UPDATE prompt_versions SET is_active = false WHERE node_name = %s AND is_active":
            (node_name,) = params
            rows = self._prompt_rows.get(node_name, [])
            count = 0
            for r in rows:
                if r["is_active"]:
                    r["is_active"] = False
                    count += 1
            self.rowcount = count
            self._result = None
        elif normalized.startswith("INSERT INTO prompt_versions"):
            node_name, _node_name_again, content, source, created_by, metadata, is_active = params
            rows = self._prompt_rows.setdefault(node_name, [])
            new_version = max((r["version"] for r in rows), default=0) + 1
            rows.append(
                {
                    "version": new_version,
                    "content": content,
                    "source": source,
                    "created_by": created_by,
                    "metadata": metadata.obj if hasattr(metadata, "obj") else metadata,
                    "is_active": bool(is_active),
                    "created_at": "2024-01-01T00:00:00Z",
                }
            )
            self._result = ("one", new_version)
        elif normalized == "UPDATE prompt_versions SET is_active = true WHERE node_name = %s AND version = %s":
            node_name, version = params
            rows = self._prompt_rows.get(node_name, [])
            match = next((r for r in rows if r["version"] == version), None)
            if match is not None:
                match["is_active"] = True
                self.rowcount = 1
            else:
                self.rowcount = 0
            self._result = None
        else:
            raise AssertionError(f"Unexpected SQL in stub cursor: {sql!r}")

    def fetchone(self):
        kind, value = self._result
        if kind == "one_row":
            return value
        assert kind == "one"
        return (value,) if value is not None else None

    def fetchall(self):
        kind, value = self._result
        assert kind == "all"
        return value


class _StubSyncConnection:
    """Stands in for psycopg.Connection, backed by an in-memory dict (for
    ConfigService's flat qa_config key/value rows) plus a per-node-name
    list of row-dicts (for PromptService's prompt_versions table)."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.store: dict = {}
        self.prompt_rows: dict = {}
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return _StubCursor(self.store, self.fail, self.prompt_rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _StubAsyncConnection:
    def __init__(self, pool: "_StubAsyncPool"):
        self._pool = pool

    async def execute(self, sql, params=None):
        if self._pool.fail:
            raise RuntimeError("stub async connection failure")
        self._pool.executed.append((sql, params))


class _StubAsyncConnectionContext:
    def __init__(self, pool: "_StubAsyncPool"):
        self._pool = pool

    async def __aenter__(self):
        return _StubAsyncConnection(self._pool)

    async def __aexit__(self, *exc_info):
        return False


class _StubAsyncPool:
    """Stands in for psycopg_pool.AsyncConnectionPool. `fail` governs every
    execute() call (including the schema-ensure DDL); `fail_on_open`
    governs only pool.open(), to exercise LogService's "disable after one
    failed _ensure_ready" behavior independently of per-write failures."""

    def __init__(self, fail: bool = False, fail_on_open: bool = False):
        self.fail = fail
        self.fail_on_open = fail_on_open
        self.closed = True
        self.open_calls = 0
        self.executed: list = []

    async def open(self, wait: bool = True, timeout: float = 5):
        self.open_calls += 1
        if self.fail_on_open:
            raise RuntimeError("stub pool failed to open")
        self.closed = False

    async def close(self):
        self.closed = True

    def connection(self):
        return _StubAsyncConnectionContext(self)
