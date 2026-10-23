"""Shared hand-rolled stubs for the Postgres-backed services (ConfigService,
LogService). Follows the repo's existing no-mocking-framework convention
(see _StubQdrantClient/_StubEmbeddings in test_rag_service.py) -- promoted
here since two services would otherwise duplicate near-identical
stub-connection boilerplate."""


class _StubCursor:
    """Stands in for a psycopg cursor. Recognizes the handful of SQL shapes
    ConfigService actually issues rather than parsing arbitrary SQL."""

    def __init__(self, store: dict, fail: bool):
        self._store = store
        self._fail = fail
        self._result = None

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
        else:
            raise AssertionError(f"Unexpected SQL in stub cursor: {sql!r}")

    def fetchone(self):
        kind, value = self._result
        assert kind == "one"
        return (value,) if value is not None else None

    def fetchall(self):
        kind, value = self._result
        assert kind == "all"
        return value


class _StubSyncConnection:
    """Stands in for psycopg.Connection, backed by an in-memory dict."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.store: dict = {}
        self.closed = False
        self.commits = 0

    def cursor(self):
        return _StubCursor(self.store, self.fail)

    def commit(self):
        self.commits += 1

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
