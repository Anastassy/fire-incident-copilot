"""Tiny local JSON state file so the bridge resumes an existing State Machine run on
restart instead of creating a new one every time (`POST /runs` is idempotent given the
same Idempotency-Key + body, but we still need to *remember* which run/cursor we're on
across process restarts). Not a database -- this is a single-process, single-run
hackathon adapter; a JSON file is intentionally the simplest thing that works.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

DEFAULT_STATE_PATH = Path(".state_machine_bridge_state.json")


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, default=str))
    tmp_path.replace(path)


def clear_cursor(state: dict[str, Any]) -> None:
    """Drop the cursor (e.g. after stream.reset / 410 CURSOR_EXPIRED) while keeping run_id."""
    state.pop("cursor", None)


def new_idempotency_key(state: dict[str, Any]) -> Optional[str]:
    return state.get("run_create_idempotency_key")
