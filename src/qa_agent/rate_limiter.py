import asyncio
import time
from collections import deque

from qa_agent.config import Settings
from qa_agent.control.pid import PIDController, PIDGains

_MINUTE_WINDOW_SECONDS = 60
_DAY_WINDOW_SECONDS = 24 * 60 * 60

# Per-process, per-scope call timestamps (time.monotonic()). Deliberately
# in-memory and module-level: tracking is per-run only, so this naturally
# resets on every `qa-agent` invocation rather than persisting across runs.
_minute_windows: dict[str, deque[float]] = {}
_day_windows: dict[str, deque[float]] = {}

# Loop A (adaptive rate limiting): also per-process/in-memory, same
# lifetime as the windows above. A PIDController per scope that continuously
# narrows the *effective* rpm below the configured static ceiling in
# response to real provider rate-limit errors, and lets it climb back up
# once those stop. Classification of "was this a rate-limit error" happens
# one layer up, in qa_agent.llm_router.provider_errors -- this module stays
# provider-SDK-agnostic and only takes a plain bool.
_loop_a_controllers: dict[str, PIDController] = {}
_loop_a_error_ewma: dict[str, float] = {}


class DailyQuotaExceededError(RuntimeError):
    """Raised when a scope's configured requests-per-day limit is already
    reached. Unlike a per-minute limit, waiting out a day-long window isn't
    practical for a one-shot CLI, so this fails fast instead of blocking."""

    def __init__(self, scope: str, rpd: int):
        super().__init__(
            f"Daily request quota for {scope!r} ({rpd}/day) reached for this run. "
            f"Adjust it with `qa-agent config set provider_limits '{{...}}'`, "
            f"or wait before retrying."
        )


def _prune(window: deque[float], now: float, horizon: float) -> None:
    while window and now - window[0] >= horizon:
        window.popleft()


def _seconds_to_wait(window: deque[float], now: float, horizon: float, limit: int) -> float:
    """Seconds the caller must wait before `window` has room for one more
    call under `limit` within the trailing `horizon` seconds. 0 if there's
    already room."""
    _prune(window, now, horizon)
    if len(window) < limit:
        return 0.0
    return horizon - (now - window[0])


def _effective_rpm(scope: str, ceiling_rpm: int) -> int:
    """The configured static `rpm` is a ceiling Loop A can only narrow,
    never exceed. With no controller yet for `scope` (no rate-limit error
    ever observed), this returns `ceiling_rpm` unchanged -- identical to
    pre-Loop-A behavior."""
    controller = _loop_a_controllers.get(scope)
    multiplier = controller.output if controller is not None else 1.0
    return max(1, int(ceiling_rpm * multiplier))


def _check(scope: str, settings: Settings) -> float:
    """Shared logic for both entry points below. Raises
    DailyQuotaExceededError if the day cap is already full; otherwise
    returns how many seconds to sleep for the minute cap (0 if none), and
    records this call's timestamp against both windows."""
    limits = settings.provider_limits.get(scope)
    if not limits:
        return 0.0

    now = time.monotonic()
    minute_window = _minute_windows.setdefault(scope, deque())
    day_window = _day_windows.setdefault(scope, deque())

    rpd = limits.get("rpd")
    if rpd is not None:
        day_wait = _seconds_to_wait(day_window, now, _DAY_WINDOW_SECONDS, rpd)
        if day_wait > 0:
            raise DailyQuotaExceededError(scope, rpd)

    minute_wait = 0.0
    rpm = limits.get("rpm")
    if rpm is not None:
        minute_wait = _seconds_to_wait(minute_window, now, _MINUTE_WINDOW_SECONDS, _effective_rpm(scope, rpm))

    record_at = now + minute_wait
    minute_window.append(record_at)
    day_window.append(record_at)
    return minute_wait


async def enforce_limit_async(scope: str, settings: Settings) -> None:
    """Call before an async chat/embedding request. Blocks (sleeps) to stay
    under the configured requests-per-minute cap; raises
    DailyQuotaExceededError immediately if the requests-per-day cap is
    already full. No-ops if `scope` has no configured limits."""
    wait = _check(scope, settings)
    if wait > 0:
        await asyncio.sleep(wait)


def enforce_limit_sync(scope: str, settings: Settings) -> None:
    """Sync counterpart of `enforce_limit_async`, for the non-async
    embedding ingestion call sites."""
    wait = _check(scope, settings)
    if wait > 0:
        time.sleep(wait)


def _loop_a_gains(settings: Settings) -> PIDGains:
    """Default kp is deliberately derived from `loop_a_target_error_rate`,
    not a flat constant: at clean steady state (EWMA == 0), `error`
    permanently sits at `+target_error_rate` (see record_call_outcome's
    docstring for why), so kp must be large enough that `kp * target_error_
    rate` alone reaches the output ceiling (1.0) -- otherwise even one
    clean call collapses the optimistic ceiling start down to a much
    smaller number on its very first (dt=0, pure-proportional) update."""
    gains = settings.loop_a_pid_gains
    target = settings.loop_a_target_error_rate
    default_kp = (1.0 / target) if target > 0 else 20.0
    return PIDGains(kp=gains.get("kp", default_kp), ki=gains.get("ki", default_kp / 4), kd=gains.get("kd", 0.0))


def record_call_outcome(scope: str, settings: Settings, *, hit_rate_limit: bool) -> None:
    """Feed Loop A with the outcome of one attempted call against `scope`.
    No-ops if `scope` has no configured `rpm` ceiling -- nothing to adapt.

    `hit_rate_limit` is a plain bool deliberately -- this module has no
    knowledge of provider SDK exception types; that classification is the
    caller's job (qa_agent.llm_router.provider_errors / ModelRouter).

    The target error rate is deliberately a small positive value, not 0.0:
    with a 0.0 setpoint the controller could only ever cut the multiplier
    down on a breach and would have no mechanism to climb back toward the
    ceiling afterward (once the error-rate EWMA settles at 0, `error =
    setpoint - 0 = 0` contributes nothing to any PID term -- permanent
    throttling, no recovery). A small positive setpoint means once
    breaches stop, `error` is small and positive, and the integral term
    slowly drags the multiplier back up -- genuine AIMD-like recovery.
    """
    limits = settings.provider_limits.get(scope)
    ceiling_rpm = limits.get("rpm") if limits else None
    if ceiling_rpm is None:
        return

    controller = _loop_a_controllers.get(scope)
    if controller is None:
        controller = PIDController(
            _loop_a_gains(settings),
            output_min=settings.loop_a_min_multiplier,
            output_max=1.0,
            initial_output=1.0,  # optimistic: start at the full ceiling
        )
        _loop_a_controllers[scope] = controller
        _loop_a_error_ewma[scope] = 0.0

    alpha = settings.loop_a_error_rate_ewma_alpha
    sample = 1.0 if hit_rate_limit else 0.0
    _loop_a_error_ewma[scope] = (1 - alpha) * _loop_a_error_ewma[scope] + alpha * sample
    controller.update(setpoint=settings.loop_a_target_error_rate, measured_value=_loop_a_error_ewma[scope])
