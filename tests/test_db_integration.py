import os
import uuid

import pytest

from qa_agent.config import get_settings
from qa_agent.db.config_service import ConfigService
from qa_agent.db.log_service import LogService
from qa_agent.db.prompt_service import PromptService

pytestmark = pytest.mark.integration

REQUIRED_ENV = ("QA_LOGS_DATABASE_URL", "QA_CONFIG_DATABASE_URL")


@pytest.fixture
def real_services():
    if any(not os.environ.get(var) for var in REQUIRED_ENV):
        pytest.skip(f"Set {', '.join(REQUIRED_ENV)} to run DB integration tests.")
    get_settings.cache_clear()
    settings = get_settings()
    return (
        ConfigService.from_settings(settings),
        LogService.from_settings(settings),
        PromptService.from_settings(settings),
    )


async def test_config_set_get_round_trips_against_real_postgres(real_services):
    config_service, _, _ = real_services
    key = f"integration-test-{uuid.uuid4().hex[:8]}"

    config_service.set(key, {"nested": True, "count": 3})

    assert config_service.get(key) == {"nested": True, "count": 3}
    assert config_service.get_all()[key] == {"nested": True, "count": 3}


async def test_log_run_start_and_end_round_trip_against_real_postgres(real_services):
    _, log_service, _ = real_services
    run_id = f"integration-test-{uuid.uuid4().hex[:8]}"

    await log_service.log_run_start(run_id, "https://example.com", "reqs", "groq", "model", "2026-01-01T00:00:00Z")
    await log_service.log_run_end(run_id, "pass", 0, 1, "2026-01-01T00:00:01Z")

    assert log_service.enabled


def test_prompt_service_create_activate_round_trips_against_real_postgres(real_services):
    _, _, prompt_service = real_services
    node_name = f"integration-test-{uuid.uuid4().hex[:8]}"

    v1 = prompt_service.create_version(node_name, "prompt v1")
    v2 = prompt_service.create_version(node_name, "prompt v2")
    assert (v1, v2) == (1, 2)

    content, version = prompt_service.get_active_version(node_name, "DEFAULT")
    assert (content, version) == ("prompt v2", 2)

    prompt_service.activate(node_name, 1)
    content, version = prompt_service.get_active_version(node_name, "DEFAULT")
    assert (content, version) == ("prompt v1", 1)
