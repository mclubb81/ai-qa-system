import pytest
from conftest import _StubSyncConnection

from qa_agent.config import Settings
from qa_agent.db.prompt_service import PromptService


def _settings() -> Settings:
    return Settings()


def test_get_active_version_returns_default_when_disabled():
    service = PromptService(None, _settings())
    content, version = service.get_active_version("planner", "DEFAULT PROMPT")
    assert content == "DEFAULT PROMPT"
    assert version is None


def test_get_active_version_returns_default_when_no_active_row():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())
    content, version = service.get_active_version("planner", "DEFAULT PROMPT")
    assert content == "DEFAULT PROMPT"
    assert version is None


def test_get_active_version_swallows_query_failure_and_returns_default():
    conn = _StubSyncConnection(fail=True)
    service = PromptService(conn, _settings())
    content, version = service.get_active_version("planner", "DEFAULT PROMPT")
    assert content == "DEFAULT PROMPT"
    assert version is None


def test_list_versions_returns_empty_when_disabled():
    service = PromptService(None, _settings())
    assert service.list_versions("planner") == []


def test_create_version_raises_when_disabled():
    service = PromptService(None, _settings())
    with pytest.raises(RuntimeError):
        service.create_version("planner", "a prompt")


def test_create_version_increments_per_node_and_activates_by_default():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())

    v1 = service.create_version("planner", "prompt v1")
    v2 = service.create_version("planner", "prompt v2")
    assert v1 == 1
    assert v2 == 2

    content, version = service.get_active_version("planner", "DEFAULT")
    assert content == "prompt v2"
    assert version == 2

    versions = service.list_versions("planner")
    assert [v.version for v in versions] == [1, 2]
    assert [v.is_active for v in versions] == [False, True]


def test_create_version_without_activate_leaves_prior_version_active():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())

    service.create_version("planner", "prompt v1")
    service.create_version("planner", "prompt v2", activate=False)

    content, version = service.get_active_version("planner", "DEFAULT")
    assert content == "prompt v1"
    assert version == 1


def test_version_numbering_is_independent_per_node():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())

    service.create_version("planner", "p1")
    v = service.create_version("analyzer", "a1")
    assert v == 1


def test_activate_raises_for_unknown_version():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())
    service.create_version("planner", "p1")
    with pytest.raises(ValueError):
        service.activate("planner", 99)


def test_activate_switches_the_active_version():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())
    service.create_version("planner", "p1")
    service.create_version("planner", "p2")

    service.activate("planner", 1)

    content, version = service.get_active_version("planner", "DEFAULT")
    assert content == "p1"
    assert version == 1


def test_revert_to_default_deactivates_without_deleting_history():
    conn = _StubSyncConnection()
    service = PromptService(conn, _settings())
    service.create_version("planner", "p1")

    service.revert_to_default("planner")

    content, version = service.get_active_version("planner", "DEFAULT")
    assert content == "DEFAULT"
    assert version is None
    assert len(service.list_versions("planner")) == 1


def test_revert_to_default_raises_when_disabled():
    service = PromptService(None, _settings())
    with pytest.raises(RuntimeError):
        service.revert_to_default("planner")
