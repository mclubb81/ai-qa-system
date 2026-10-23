import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from qa_agent.config import Settings, get_settings

if TYPE_CHECKING:
    import psycopg
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def get_config_dsn(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    return settings.qa_config_database_url or None


def get_logs_dsn(settings: Settings | None = None) -> str | None:
    settings = settings or get_settings()
    return settings.qa_logs_database_url or None


def get_sync_connection(dsn: str) -> "psycopg.Connection | None":
    """Open a short-lived sync connection for the config bootstrap path.
    Never raises -- returns None (with a warning) on failure. The caller
    owns closing it."""
    try:
        import psycopg

        return psycopg.connect(dsn, connect_timeout=5)
    except Exception:
        logger.warning("Could not connect to qa_config DB", exc_info=True)
        return None


@lru_cache
def _build_logs_pool(dsn: str) -> "AsyncConnectionPool":
    """Construct (but do not open) the async pool. Caches on the DSN
    string, not the Settings object, since pydantic settings instances
    aren't hashable -- same approach as rag/client.py's `_build_client`."""
    from psycopg_pool import AsyncConnectionPool

    return AsyncConnectionPool(dsn, min_size=1, max_size=5, open=False)


def get_logs_pool(settings: Settings | None = None) -> "AsyncConnectionPool | None":
    """Lazily build (cached) the qa_logs pool object, or None if
    unconfigured. Construction never raises -- `AsyncConnectionPool(open=False)`
    performs no I/O; opening it is deferred to LogService on first use,
    since that requires `await`."""
    dsn = get_logs_dsn(settings)
    if not dsn:
        return None
    return _build_logs_pool(dsn)
