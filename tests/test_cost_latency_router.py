from qa_agent.config import Settings
from qa_agent.llm_router.cost_latency import CostLatencyRouter


class _StubRouterStateStore:
    """Plain dict-backed fake, same convention as _StubRagService in
    test_triage_node.py -- not real Postgres."""

    def __init__(self):
        self._store: dict = {}

    @property
    def enabled(self) -> bool:
        return True

    def get(self, name, default=None):
        return self._store.get(name, default)

    def set(self, name, value) -> None:
        self._store[name] = value


def _router(settings: Settings | None = None) -> tuple[CostLatencyRouter, _StubRouterStateStore]:
    store = _StubRouterStateStore()
    return CostLatencyRouter(store, settings or Settings()), store


def test_unmeasured_provider_scores_none():
    router, _ = _router()
    assert router.score("groq") is None


def test_record_lowers_score_for_a_fast_call():
    router, _ = _router()
    router.record("groq", duration_ms=100.0)
    first_score = router.score("groq")
    assert first_score is not None
    assert first_score >= 0.0


def test_record_raises_score_for_a_slow_call_relative_to_a_fast_one():
    fast_router, _ = _router()
    slow_router, _ = _router()
    fast_router.record("groq", duration_ms=100.0)
    slow_router.record("groq", duration_ms=10_000.0)
    assert slow_router.score("groq") > fast_router.score("groq")


def test_higher_cost_weight_raises_score_for_identical_latency():
    settings = Settings(provider_cost_weights={"anthropic": 5.0, "groq": 1.0})
    router, _ = _router(settings)
    router.record("groq", duration_ms=1000.0)
    router.record("anthropic", duration_ms=1000.0)
    assert router.score("anthropic") > router.score("groq")


def test_state_persists_through_the_store():
    store = _StubRouterStateStore()
    router_a = CostLatencyRouter(store, Settings())
    router_a.record("groq", duration_ms=500.0)
    score_from_a = router_a.score("groq")

    # A fresh CostLatencyRouter instance backed by the SAME store (as if
    # a new CLI process started up) should see the persisted score rather
    # than starting neutral.
    router_b = CostLatencyRouter(store, Settings())
    assert router_b.score("groq") == score_from_a


def test_rank_orders_ascending_by_score_lower_is_better():
    router, _ = _router()
    router.record("slow", duration_ms=10_000.0)
    router.record("fast", duration_ms=10.0)
    assert router.rank(["slow", "fast"]) == ["fast", "slow"]


def test_rank_sorts_unscored_providers_after_scored_ones():
    router, _ = _router()
    router.record("known", duration_ms=100.0)
    assert router.rank(["unknown", "known"]) == ["known", "unknown"]


def test_rank_falls_back_to_candidate_order_when_all_unscored():
    router, _ = _router()
    assert router.rank(["b", "a", "c"]) == ["b", "a", "c"]


def test_rank_falls_back_to_candidate_order_on_a_tie():
    router, _ = _router()
    router.record("first", duration_ms=100.0)
    router.record("second", duration_ms=100.0)
    assert router.rank(["second", "first"]) == ["second", "first"]
