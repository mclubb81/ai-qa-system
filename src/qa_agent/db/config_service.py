import logging
from typing import TYPE_CHECKING, Any

from qa_agent.config import Settings, get_settings
from qa_agent.db.client import get_config_dsn, get_sync_connection
from qa_agent.db.schema import ensure_config_schema

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


class ConfigService:
    """Postgres-backed JSON config, DI'd exactly like RagService: `enabled`
    is the single source of truth, reads never raise (fall back to
    `default`/`{}` on failure), `set` raises when disabled since it's an
    explicit `qa-agent config set` write, same as RagService.upsert_docs."""

    def __init__(self, connection: "psycopg.Connection | None", settings: Settings):
        self._conn = connection
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ConfigService":
        settings = settings or get_settings()
        dsn = get_config_dsn(settings)
        conn = get_sync_connection(dsn) if dsn else None
        if conn is not None:
            try:
                ensure_config_schema(conn)
            except Exception:
                logger.warning("Could not ensure qa_config schema", exc_info=True)
                conn.close()
                conn = None
        return cls(conn, settings)

    def get(self, key: str, default: Any = None) -> Any:
        if self._conn is None:
            return default
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT value FROM qa_config WHERE key = %s", (key,))
                row = cur.fetchone()
            return row[0] if row else default
        except Exception:
            logger.warning("ConfigService.get(%r) failed", key, exc_info=True)
            return default

    def get_all(self) -> dict[str, Any]:
        if self._conn is None:
            return {}
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT key, value FROM qa_config")
                rows = cur.fetchall()
            return dict(rows)
        except Exception:
            logger.warning("ConfigService.get_all() failed", exc_info=True)
            return {}

    def set(self, key: str, value: Any) -> None:
        if self._conn is None:
            raise RuntimeError("Config DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        from psycopg.types.json import Json

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO qa_config (key, value, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, Json(value)),
            )
        self._conn.commit()

    def delete(self, key: str) -> None:
        """Remove a stored override, letting that key fall back to its
        .env/hardcoded default again. Raises when disabled, same as set()."""
        if self._conn is None:
            raise RuntimeError("Config DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM qa_config WHERE key = %s", (key,))
        self._conn.commit()
