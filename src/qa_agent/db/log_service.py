import logging
from typing import TYPE_CHECKING

from qa_agent.config import Settings, get_settings
from qa_agent.db.client import get_logs_pool
from qa_agent.db.schema import ensure_logs_schema
from qa_agent.utils.ids import now_iso

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class LogService:
    """Postgres-backed structured logging for one run's lifetime. Unlike
    RagService/ConfigService, EVERY method here (reads and writes alike --
    though this class only ever writes) swallows its own exceptions: these
    calls happen mid-run, inside LangGraph node execution, and must never
    interrupt or measurably stall a live QA session."""

    def __init__(self, pool: "AsyncConnectionPool | None", settings: Settings):
        self._pool = pool
        self._settings = settings
        self._ready = False

    @property
    def enabled(self) -> bool:
        return self._pool is not None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "LogService":
        settings = settings or get_settings()
        return cls(get_logs_pool(settings), settings)

    async def _ensure_ready(self) -> bool:
        """Open the pool + ensure schema exactly once per instance (i.e.
        once per run). On failure, permanently disables this instance for
        the rest of the run instead of retrying on every subsequent log
        call."""
        if self._pool is None:
            return False
        if self._ready:
            return True
        try:
            if self._pool.closed:
                await self._pool.open(wait=True, timeout=5)
            await ensure_logs_schema(self._pool)
            self._ready = True
        except Exception:
            logger.warning("qa_logs DB unavailable; logging disabled for this run", exc_info=True)
            self._pool = None
        return self._pool is not None

    async def _execute(self, sql: str, params: tuple) -> None:
        if not await self._ensure_ready() or self._pool is None:
            return
        try:
            async with self._pool.connection() as conn:
                await conn.execute(sql, params)
        except Exception:
            logger.warning("LogService write failed", exc_info=True)

    async def log_run_start(
        self,
        run_id: str,
        target_url: str,
        requirements_summary: str,
        llm_provider: str,
        llm_model: str,
        started_at: str,
    ) -> None:
        await self._execute(
            """INSERT INTO runs (run_id, target_url, requirements_summary, llm_provider, llm_model, started_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (run_id) DO NOTHING""",
            (run_id, target_url, requirements_summary, llm_provider, llm_model, started_at),
        )

    async def log_run_end(
        self,
        run_id: str,
        overall_status: str,
        bug_count: int,
        test_case_count: int,
        finished_at: str,
        error: str | None = None,
    ) -> None:
        await self._execute(
            """UPDATE runs SET overall_status=%s, bug_count=%s, test_case_count=%s,
                                finished_at=%s, error=%s
               WHERE run_id=%s""",
            (overall_status, bug_count, test_case_count, finished_at, error, run_id),
        )

    async def log_node_transition(
        self,
        run_id: str,
        node_name: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        ok: bool = True,
    ) -> None:
        await self._execute(
            """INSERT INTO node_events (run_id, node_name, started_at, finished_at, duration_ms, ok)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (run_id, node_name, started_at, finished_at, duration_ms, ok),
        )

    async def log_llm_call(
        self,
        run_id: str,
        node_name: str,
        provider: str,
        model: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        prompt_chars: int,
        response_chars: int,
        ok: bool = True,
    ) -> None:
        await self._execute(
            """INSERT INTO llm_calls (run_id, node_name, provider, model, started_at, finished_at,
                                       duration_ms, prompt_chars, response_chars, ok)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, node_name, provider, model, started_at, finished_at,
             duration_ms, prompt_chars, response_chars, ok),
        )

    async def log_error(
        self,
        run_id: str | None,
        node_name: str | None,
        message: str,
        stack_trace: str | None = None,
        occurred_at: str | None = None,
    ) -> None:
        await self._execute(
            """INSERT INTO errors (run_id, node_name, occurred_at, message, stack_trace)
               VALUES (%s, %s, %s, %s, %s)""",
            (run_id, node_name, occurred_at or now_iso(), message, stack_trace),
        )
