import re

from qa_agent.utils.ids import new_run_id


def test_new_run_id_keeps_a_sortable_timestamp_prefix():
    run_id = new_run_id()
    assert re.match(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$", run_id)


def test_new_run_id_is_unique_across_rapid_successive_calls():
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50
