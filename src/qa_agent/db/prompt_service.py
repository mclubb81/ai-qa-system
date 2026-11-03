import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from qa_agent.config import Settings, get_settings
from qa_agent.db.client import get_config_dsn, get_sync_connection
from qa_agent.db.schema import ensure_prompts_schema

if TYPE_CHECKING:
    import psycopg

logger = logging.getLogger(__name__)


@dataclass
class PromptVersionRecord:
    node_name: str
    version: int
    content: str
    source: str
    created_by: str | None
    metadata: dict[str, Any] | None
    is_active: bool
    created_at: str


class PromptService:
    """Postgres-backed, versioned agent system prompts. Lives in the same
    `qa_config` database as ConfigService (a separate table, not a third
    DB), DI'd the same way: `enabled` is the single source of truth, reads
    never raise (fall back to the hardcoded `*_SYSTEM_PROMPT` default on
    any failure), writes raise when disabled since they're explicit
    `qa-agent prompts set`/web-form actions, same as ConfigService.set.

    History is append-only -- `revert_to_default` and re-activating an
    older version never delete a row, only flip `is_active`.
    """

    def __init__(self, connection: "psycopg.Connection | None", settings: Settings):
        self._conn = connection
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._conn is not None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "PromptService":
        settings = settings or get_settings()
        dsn = get_config_dsn(settings)
        conn = get_sync_connection(dsn) if dsn else None
        if conn is not None:
            try:
                ensure_prompts_schema(conn)
            except Exception:
                logger.warning("Could not ensure prompt_versions schema", exc_info=True)
                conn.close()
                conn = None
        return cls(conn, settings)

    def get_active_version(self, node_name: str, default: str) -> tuple[str, int | None]:
        """Never raises. Returns (default, None) when disabled, on query
        failure, or when no version is currently active for node_name."""
        if self._conn is None:
            return default, None
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT content, version FROM prompt_versions WHERE node_name = %s AND is_active LIMIT 1",
                    (node_name,),
                )
                row = cur.fetchone()
            if row is None:
                return default, None
            content, version = row
            return content, version
        except Exception:
            logger.warning("PromptService.get_active_version(%r) failed", node_name, exc_info=True)
            return default, None

    def list_versions(self, node_name: str) -> list[PromptVersionRecord]:
        """Never raises; returns [] when disabled/on failure. Ordered by
        version ascending."""
        if self._conn is None:
            return []
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    """SELECT node_name, version, content, source, created_by, metadata,
                              is_active, created_at
                       FROM prompt_versions WHERE node_name = %s ORDER BY version ASC""",
                    (node_name,),
                )
                rows = cur.fetchall()
            return [PromptVersionRecord(*row) for row in rows]
        except Exception:
            logger.warning("PromptService.list_versions(%r) failed", node_name, exc_info=True)
            return []

    def list_all(self, node_names: list[str]) -> dict[str, list[PromptVersionRecord]]:
        """Convenience for web/CLI list views: node_name -> its versions."""
        return {name: self.list_versions(name) for name in node_names}

    def create_version(
        self,
        node_name: str,
        content: str,
        *,
        source: str = "manual",
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
        activate: bool = True,
    ) -> int:
        """Raises RuntimeError when disabled -- explicit write, same
        contract as ConfigService.set. Assigns the next version number
        for node_name (1, 2, 3, ...) and, if activate=True, deactivates
        whichever version is currently active first, all in one
        transaction. Returns the new version number.

        Known limitation: the version-number SELECT MAX(...)+1 has a
        small race window under *concurrent* writes to the same
        node_name -- acceptable given prompts are written by a human or
        an infrequent batch process, not high-throughput telemetry.
        """
        if self._conn is None:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        from psycopg.types.json import Json

        with self._conn.cursor() as cur:
            if activate:
                cur.execute(
                    "UPDATE prompt_versions SET is_active = false WHERE node_name = %s AND is_active",
                    (node_name,),
                )
            cur.execute(
                """
                INSERT INTO prompt_versions (node_name, version, content, source, created_by, metadata, is_active)
                VALUES (
                    %s,
                    (SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_versions WHERE node_name = %s),
                    %s, %s, %s, %s, %s
                )
                RETURNING version
                """,
                (
                    node_name,
                    node_name,
                    content,
                    source,
                    created_by,
                    Json(metadata) if metadata is not None else None,
                    activate,
                ),
            )
            (new_version,) = cur.fetchone()
        self._conn.commit()
        return new_version

    def activate(self, node_name: str, version: int) -> None:
        """Raises RuntimeError when disabled. Raises ValueError if
        (node_name, version) doesn't exist. Deactivates whichever row is
        currently active for node_name, then activates the target row, in
        one transaction."""
        if self._conn is None:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE prompt_versions SET is_active = false WHERE node_name = %s AND is_active",
                (node_name,),
            )
            cur.execute(
                "UPDATE prompt_versions SET is_active = true WHERE node_name = %s AND version = %s",
                (node_name, version),
            )
            activated = cur.rowcount
        if activated == 0:
            self._conn.rollback()
            raise ValueError(f"No such prompt version: node={node_name!r} version={version!r}")
        self._conn.commit()

    def revert_to_default(self, node_name: str) -> None:
        """Raises RuntimeError when disabled. Deactivates the currently
        active row (if any) for node_name, leaving zero active rows --
        get_active_version then falls back to the hardcoded default.
        Does not delete any row; history is preserved."""
        if self._conn is None:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE prompt_versions SET is_active = false WHERE node_name = %s AND is_active",
                (node_name,),
            )
        self._conn.commit()
