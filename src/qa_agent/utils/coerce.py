import json
from typing import Any


def coerce_value(raw: str) -> Any:
    """Try to parse as JSON (so `3`, `false`, `[1,2]` etc. store as real
    JSON types) and fall back to the raw string otherwise."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
