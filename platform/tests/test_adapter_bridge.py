"""Tests for the run-id subscription behavior in app.adapter.bridge.Bridge.

Per the simulator team's deployment handoff
(raw-source/state-consumer-handoff/.../START_HERE.ru.md section 3), a production
consumer must subscribe to one externally-agreed, shared run_id rather than creating
its own, and must never send Play to it. Local dev/testing keeps creating (and playing)
its own run -- these tests only cover the new "shared run_id configured" branch; the
default/local behavior is already exercised end-to-end by tests/test_adapter_mapper.py
importing the module cleanly and by manual verification (see prior session report).

No real network/SSE connection is used -- StateMachineClient is replaced with a small
recording fake matching just the methods Bridge calls, following the same "no mocking
framework, just plain fixtures/fakes" style as tests/test_adapter_mapper.py.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapter.bridge import Bridge


class _RecordingStateMachineClient:
    """Fake StateMachineClient: records calls, never talks to a real server. In
    shared-run-id mode, Bridge must never call create_run or send_command on this."""

    def __init__(self) -> None:
        self.create_run_calls: list[tuple[Any, ...]] = []
        self.send_command_calls: list[tuple[Any, ...]] = []
        self._frames: list[tuple[str, dict]] = []

    def queue_frames(self, frames: list[tuple[str, dict]]) -> None:
        self._frames = frames

    async def create_run(self, scenario_id, idempotency_key, speed=1):
        self.create_run_calls.append((scenario_id, idempotency_key, speed))
        raise AssertionError("create_run must not be called when a shared run_id is configured")

    async def send_command(self, run_id, expected_generation, action, **extra):
        self.send_command_calls.append((run_id, expected_generation, action))
        raise AssertionError("send_command must not be called when a shared run_id is configured")

    async def stream(self, run_id, cursor=None):
        for frame in self._frames:
            yield frame


def _make_bridge(client: _RecordingStateMachineClient, tmp_path, run_id=None) -> Bridge:
    return Bridge(
        state_machine=client,
        our_api_base_url="http://localhost:8000",
        api_key="test-key",
        scenario_id="degraded",
        run_id=run_id,
        state_path=tmp_path / "state.json",
    )


@pytest.mark.asyncio
async def test_ensure_run_uses_configured_run_id_without_creating_one(tmp_path):
    client = _RecordingStateMachineClient()
    bridge = _make_bridge(client, tmp_path, run_id="shared-run-123")

    run_id = await bridge._ensure_run()

    assert run_id == "shared-run-123"
    assert client.create_run_calls == []


@pytest.mark.asyncio
async def test_ensure_run_creates_local_run_when_no_run_id_configured(tmp_path):
    """Unchanged default behavior: no configured run_id -> create our own local run."""
    client = _RecordingStateMachineClient()

    async def create_run(scenario_id, idempotency_key, speed=1):
        client.create_run_calls.append((scenario_id, idempotency_key, speed))
        return {"run_id": "local-run-1", "generation": 0}

    client.create_run = create_run  # type: ignore[method-assign]
    bridge = _make_bridge(client, tmp_path, run_id=None)

    run_id = await bridge._ensure_run()

    assert run_id == "local-run-1"
    assert len(client.create_run_calls) == 1
    assert client.create_run_calls[0][0] == "degraded"


@pytest.mark.asyncio
async def test_maybe_play_never_invoked_for_shared_run_id(tmp_path):
    """A snapshot reporting status=paused would normally trigger Play in local mode;
    in shared-run-id mode it must not, per the handoff doc ("не включай Play при
    подписке"). We assert this via the client's send_command never being called
    (_maybe_play's only externally-observable effect), rather than mocking a private
    method, so the test exercises the real guard in Bridge._run_once."""
    client = _RecordingStateMachineClient()
    client.queue_frames(
        [
            (
                "snapshot",
                {
                    "run": {"generation": 0, "status": "paused"},
                    "as_of": {"cursor": "shared-run-123:0"},
                    "devices": [],
                },
            )
        ]
    )
    bridge = _make_bridge(client, tmp_path, run_id="shared-run-123")

    clean_reconnect = await bridge._run_once("shared-run-123")

    assert client.send_command_calls == []
    # The fake stream ends right after the snapshot frame (no stream.reset / heartbeat
    # bump) -- an unexpected-end reconnect, not one of the intentional ones.
    assert clean_reconnect is False
