from datetime import UTC, datetime
from uuid import uuid4


def new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex[:8]}"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
