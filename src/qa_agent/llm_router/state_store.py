import logging
from typing import Any

from qa_agent.db.config_service import ConfigService

logger = logging.getLogger(__name__)

# Reserved namespace: deliberately not a Settings field name, so it is
# never read through get_effective_settings()'s overlay (that overlay only
# takes effect for keys matching a Settings field). Keeps "things a user
# tunes via `qa-agent config set`" and "state the router itself writes"
# unambiguous, even though both live in the same qa_config table/
# ConfigService.
_KEY_PREFIX = "_router_state/"


class RouterStateStore:
    """Thin wrapper around ConfigService for router-learned state (Loop B's
    per-provider PID state). Unlike ConfigService.set, `set` here never
    raises: this is router-internal bookkeeping, not an explicit user
    `qa-agent config set` action, so it must degrade to a per-run no-op
    when qa_config isn't configured -- same graceful-degradation contract
    as RagService/LogService."""

    def __init__(self, config_service: ConfigService):
        self._config = config_service

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def get(self, name: str, default: Any = None) -> Any:
        return self._config.get(f"{_KEY_PREFIX}{name}", default)

    def set(self, name: str, value: Any) -> None:
        try:
            self._config.set(f"{_KEY_PREFIX}{name}", value)
        except Exception:
            logger.debug(
                "RouterStateStore.set(%r) failed/disabled; continuing without persistence", name, exc_info=True
            )
