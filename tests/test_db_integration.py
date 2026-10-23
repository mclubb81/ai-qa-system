import os
import uuid

import pytest

from qa_agent.config import get_settings
from qa_agent.db.config_service import ConfigService
from qa_agent.db.log_service import LogService

pytestmark = pytest.mark.integration

REQUIRED_ENV = ("QA_LOGS_DATABASE_URL", "QA_CONFIG_DATABASE_URL")


@pytest.fixture
def real_services():
    if any(not os.environ.get(var) for var in REQUIRED_ENV):
        pytest.skip(f"Set {', '.join(REQUIRED_ENV)} to run DB integration tests.")
    get_settings.cache_clear()
    settings = get_settings()
    return ConfigService.from_settings(settings), LogService.from_settings(settings)


async def test_config_set_get_round_trips_against_real_postgres(real_services):
    config_service, _ = real_services
    key = f"integration-test-{uuid.uuid4().hex[:8]}"

    config_service.set(key, {"nested": True, "count": 3})

    assert config_service.get(key) == {"nested": True, "count": 3}
    assert config_service.get_all()[key] == {"nested": True, "count": 3}


async def test_log_run_start_and_end_round_trip_against_real_postgres(real_services):
    _, log_service = real_services
    run_id = f"integration-test-{uuid.uuid4().hex[:8]}"

    await log_service.log_run_start(run_id, "https://example.com", "reqs", "groq", "model", "2026-01-01T00:00:00Z")
    await log_service.log_run_end(run_id, "pass", 0, 1, "2026-01-01T00:00:01Z")

    assert log_service.enabled
