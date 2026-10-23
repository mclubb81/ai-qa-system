import pytest
from conftest import _StubSyncConnection

from qa_agent.config import Settings
from qa_agent.db.config_service import ConfigService


def _settings() -> Settings:
    return Settings()


def test_get_returns_default_when_disabled():
    service = ConfigService(None, _settings())
    assert service.get("max_retries", default=1) == 1
    assert service.get("max_retries") is None


def test_get_all_returns_empty_dict_when_disabled():
    service = ConfigService(None, _settings())
    assert service.get_all() == {}


def test_set_raises_when_disabled():
    service = ConfigService(None, _settings())
    with pytest.raises(RuntimeError):
        service.set("max_retries", 3)


def test_set_then_get_round_trips():
    conn = _StubSyncConnection()
    service = ConfigService(conn, _settings())

    service.set("max_retries", 3)
    service.set("llm_provider", "google")

    assert service.get("max_retries") == 3
    assert service.get("llm_provider") == "google"
    assert service.get("unset_key", default="fallback") == "fallback"
    assert conn.commits == 2


def test_get_all_returns_every_stored_key():
    conn = _StubSyncConnection()
    service = ConfigService(conn, _settings())
    service.set("max_retries", 3)
    service.set("playwright_headless", False)

    assert service.get_all() == {"max_retries": 3, "playwright_headless": False}


def test_get_swallows_query_failure_and_returns_default():
    conn = _StubSyncConnection(fail=True)
    service = ConfigService(conn, _settings())
    assert service.get("max_retries", default="fallback") == "fallback"


def test_get_all_swallows_query_failure_and_returns_empty_dict():
    conn = _StubSyncConnection(fail=True)
    service = ConfigService(conn, _settings())
    assert service.get_all() == {}
