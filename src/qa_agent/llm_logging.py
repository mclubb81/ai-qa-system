import time
from collections.abc import Awaitable, Callable
from typing import Any

from qa_agent.db.log_service import LogService
from qa_agent.utils.ids import now_iso


async def logged_llm_call(
    call: Callable[[], Awaitable[Any]],
    *,
    run_id: str,
    node_name: str,
    provider: str,
    model: str,
    log_service: LogService,
    prompt_chars: int = 0,
) -> Any:
    """Wrap a single LLM invocation with duration/size logging. `call` is a
    zero-arg thunk so this uniformly wraps every call shape used across the
    agent nodes (`structured_llm.ainvoke(messages)`, or the executor's
    `executor_agent.ainvoke({...}, config=...)`).

    Known limitation: the executor's ReAct agent may issue multiple internal
    LLM turns per `ainvoke` call -- this produces one aggregate `llm_calls`
    row per test case, not per internal turn.
    """
    started_at = now_iso()
    started = time.monotonic()
    try:
        response = await call()
    except Exception:
        duration_ms = (time.monotonic() - started) * 1000
        await log_service.log_llm_call(
            run_id, node_name, provider, model, started_at, now_iso(),
            duration_ms, prompt_chars, 0, ok=False,
        )
        raise
    duration_ms = (time.monotonic() - started) * 1000
    await log_service.log_llm_call(
        run_id, node_name, provider, model, started_at, now_iso(),
        duration_ms, prompt_chars, len(str(response)), ok=True,
    )
    return response
