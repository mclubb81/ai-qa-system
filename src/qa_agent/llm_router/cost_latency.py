import time

from qa_agent.config import Settings
from qa_agent.control.pid import PIDController, PIDGains
from qa_agent.llm_router.state_store import RouterStateStore

# Generous ceiling in ms-equivalent "badness" units -- normal
# latency*cost-weight products never approach this; it only exists so
# anti-windup has a finite range to bound against.
_SCORE_OUTPUT_MAX = 10 * 60 * 1000.0


class CostLatencyRouter:
    """Owns Loop B: one persisted PIDController per provider, tracking a
    'badness' score (lower = better) from observed latency scaled by an
    approximate relative-cost weight. Persists across CLI runs via
    RouterStateStore; degrades to neutral (every provider unscored, i.e.
    pure candidate-list-order tie-break) per-run behavior when qa_config
    isn't configured.
    """

    def __init__(self, store: RouterStateStore, settings: Settings):
        self._store = store
        self._settings = settings
        self._pids: dict[str, PIDController] = {}

    def _gains(self) -> PIDGains:
        gains = self._settings.loop_b_pid_gains
        return PIDGains(kp=gains.get("kp", 0.5), ki=gains.get("ki", 0.05), kd=gains.get("kd", 0.1))

    def _load(self, provider: str) -> PIDController:
        if provider in self._pids:
            return self._pids[provider]
        state = self._store.get(f"loop_b/{provider}")
        pid = (
            PIDController.from_state(
                self._gains(), output_min=0.0, output_max=_SCORE_OUTPUT_MAX, state=state, clock=time.time
            )
            if state
            else PIDController(
                self._gains(), output_min=0.0, output_max=_SCORE_OUTPUT_MAX, initial_output=0.0, clock=time.time
            )
        )
        self._pids[provider] = pid
        return pid

    def score(self, provider: str) -> float | None:
        """None == 'no learned preference yet' (never measured, this run
        or any prior run) -- distinct from an honest 0.0 score."""
        if provider in self._pids:
            return self._pids[provider].output
        state = self._store.get(f"loop_b/{provider}")
        return state["output"] if state else None

    def record(self, provider: str, duration_ms: float) -> None:
        weight = self._settings.provider_cost_weights.get(provider, 1.0)
        measured = duration_ms * weight
        pid = self._load(provider)
        now = time.time()
        # Clamp dt: Loop B's dt spans real wall-clock gaps, including
        # across separate CLI process runs (that's the point -- it must
        # persist). But an unbounded dt (e.g. a provider untouched for
        # days) would let one sample's integral*dt term swing the score
        # wildly on the next call, so cap it.
        prev_time = pid.get_state()["prev_time"]
        if prev_time is not None:
            now = min(now, prev_time + self._settings.loop_b_max_dt_seconds)
        # This is used as a *tracking* filter, not a classic "drive error
        # to zero" controller: the new measurement is the setpoint, and the
        # controller's own prior output is the "measured value", so
        # error = measured - prior_output pulls the score toward whatever
        # samples keep arriving (decaying old influence), rather than
        # monotonically accumulating raw badness forever. Passing
        # setpoint=0/measured_value=measured instead would mean every call
        # starts from error = -measured (always <= 0), which on the very
        # first (dt=0, pure-proportional) call for a provider collapses
        # straight to the output floor regardless of how good or bad that
        # first call actually was.
        pid.update(setpoint=measured, measured_value=pid.output, now=now)
        self._store.set(f"loop_b/{provider}", pid.get_state())

    def rank(self, candidates: list[str]) -> list[str]:
        """Sort ascending by score (lower = better); unscored providers
        sort after ALL scored ones (don't let a provider nobody has ever
        measured leapfrog a proven-good one), and ties -- including the
        all-unscored case -- fall back to `candidates`' own order. This is
        what makes the configured candidate-list order double as the
        prior/tie-break when Loop B has no learned preference yet."""
        scores = {p: self.score(p) for p in candidates}
        return sorted(
            candidates,
            key=lambda p: (scores[p] if scores[p] is not None else float("inf"), candidates.index(p)),
        )
