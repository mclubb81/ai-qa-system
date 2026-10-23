import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class PIDGains:
    kp: float
    ki: float
    kd: float


class PIDController:
    """Generic, stateful PID controller -- no knowledge of providers, rate
    limits, or qa_agent config. One instance per controlled variable; never
    share an instance across scopes/providers, since the integral/derivative
    state below is per-instance.

    `update()` derives `dt` from wall-clock time elapsed since the previous
    call via `clock` (injected so callers can use `time.monotonic` for
    state that only needs to make sense within one process, or `time.time`
    for state meant to survive across process restarts), or an explicit
    `now` for deterministic tests.
    """

    def __init__(
        self,
        gains: PIDGains,
        *,
        output_min: float,
        output_max: float,
        initial_output: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if output_min > output_max:
            raise ValueError("output_min must be <= output_max")
        self._gains = gains
        self._output_min = output_min
        self._output_max = output_max
        self._clock = clock
        self._integral = 0.0
        self._prev_error: float | None = None
        self._prev_time: float | None = None
        self.output = self._clamp(output_max if initial_output is None else initial_output)

    def _clamp(self, value: float) -> float:
        return max(self._output_min, min(self._output_max, value))

    def update(self, setpoint: float, measured_value: float, *, now: float | None = None) -> float:
        now = self._clock() if now is None else now
        error = setpoint - measured_value
        dt = 0.0 if self._prev_time is None else max(now - self._prev_time, 0.0)

        if dt > 0:
            self._integral += error * dt
            # Anti-windup: clamp the integral term to the range that alone
            # could saturate the output, so a long stretch pinned at
            # output_min/output_max doesn't build up a hidden "debt" that
            # causes overshoot once the output unclamps again.
            if self._gains.ki:
                bound = (self._output_max - self._output_min) / abs(self._gains.ki)
                self._integral = max(-bound, min(bound, self._integral))

        derivative = 0.0
        if dt > 0 and self._prev_error is not None:
            derivative = (error - self._prev_error) / dt

        raw_output = self._gains.kp * error + self._gains.ki * self._integral + self._gains.kd * derivative
        self.output = self._clamp(raw_output)

        self._prev_error = error
        self._prev_time = now
        return self.output

    def reset(self, output: float | None = None) -> None:
        self._integral = 0.0
        self._prev_error = None
        self._prev_time = None
        self.output = self._clamp(self._output_max if output is None else output)

    def get_state(self) -> dict:
        """Cross-process persistence support -- only Loop B (model
        selection cost/latency weighting) needs this; Loop A (adaptive
        rate limiting) is per-process and never serializes."""
        return {
            "integral": self._integral,
            "prev_error": self._prev_error,
            "prev_time": self._prev_time,
            "output": self.output,
        }

    @classmethod
    def from_state(
        cls,
        gains: PIDGains,
        *,
        output_min: float,
        output_max: float,
        state: dict,
        clock: Callable[[], float] = time.monotonic,
    ) -> "PIDController":
        controller = cls(
            gains,
            output_min=output_min,
            output_max=output_max,
            initial_output=state.get("output"),
            clock=clock,
        )
        controller._integral = state.get("integral", 0.0)
        controller._prev_error = state.get("prev_error")
        controller._prev_time = state.get("prev_time")
        return controller
