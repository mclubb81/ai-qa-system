"""In-process background jobs: bridges this project's async core (LangGraph
+ Playwright MCP, minutes-long calls) into Flask's sync request/response
cycle without any new infra (no Redis/Celery -- this is a local,
single-operator tool). Each job runs in its own daemon thread via
`asyncio.run(...)`; state lives only in the module-level `JOBS` registry for
the lifetime of the process. That's an accepted tradeoff, not a bug: the
durable artifact of a run (`report.json`) is already written to disk by
`run_qa_session` independent of this registry.
"""

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from qa_agent.utils.ids import now_iso

logger = logging.getLogger(__name__)

JobKind = Literal["run", "heal"]
JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class Job:
    job_id: str
    kind: JobKind
    params: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = "queued"
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    result: Any = None
    error: str | None = None


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: JobKind, params: dict[str, Any]) -> Job:
        job = Job(job_id=uuid4().hex, kind=kind, params=params)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for name, value in fields.items():
                setattr(job, name, value)


JOBS = JobRegistry()


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


def run_async_job(
    registry: JobRegistry, job: Job, coro_factory: Callable[[], Awaitable[Any]]
) -> None:
    """Start `job` running in a background thread. `coro_factory` is called
    inside that thread (not here) so the caller's own async work -- e.g. an
    already-running Playwright session -- is never touched from the Flask
    request thread."""

    def _runner() -> None:
        registry._update(job.job_id, status="running", started_at=now_iso())
        try:
            result = asyncio.run(coro_factory())
        except Exception as exc:
            logger.exception("Job %s failed", job.job_id)
            registry._update(job.job_id, status="error", error=str(exc), finished_at=now_iso())
        else:
            registry._update(job.job_id, status="done", result=result, finished_at=now_iso())

    _spawn(_runner)
