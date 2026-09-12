"""Entrypoint: `python -m app.adapter.bridge`.

Long-running process (NOT wired into the FastAPI app / request lifecycle) that:

1. Creates (or resumes, via a persisted Idempotency-Key) one State Machine `run`.
2. Opens its SSE stream, sends `play`, and for every relevant event maps it
   (`app.adapter.mapper`) to a `TelemetryIn`-shaped dict and `POST`s it to OUR OWN
   `/ingest/telemetry` -- exactly like any other client of that endpoint. The rest of the
   platform (REST/SSE, MCP) doesn't need to know this data originated from a live source
   instead of curl/tests.
3. Persists run_id/generation/cursor to a small local JSON file
   (`.state_machine_bridge_state.json`, gitignored) so a restart resumes the same run and
   stream position instead of creating a new run every time.
4. Reconnects on disconnect using `Last-Event-ID`, follows `stream.reset` (generation
   bump -> reconnect without cursor for a fresh snapshot), follows `410 CURSOR_EXPIRED`
   (reconnect without cursor), and backs off (1/2/4/8/15s + jitter) on other errors --
   without retrying forever on 401/403 (see `state_machine_client.FatalAuthError`).

Continuous audio/video streaming (`/media-streams`) is explicitly out of scope for this
version; `audio_url` stays null even for mapped radio transcripts.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from typing import Any, Optional

import httpx

from app.adapter.mapper import DeviceMeta, apply_snapshot, map_event_to_telemetry_in
from app.adapter.state_machine_client import (
    FatalAuthError,
    RECONNECT_DELAYS_S,
    StateMachineClient,
    StateMachineError,
)
from app.adapter.state_store import DEFAULT_STATE_PATH, clear_cursor, load_state, save_state
from app.core.config import settings

logger = logging.getLogger("app.adapter.bridge")


class Bridge:
    def __init__(
        self,
        state_machine: StateMachineClient,
        our_api_base_url: str,
        api_key: str,
        scenario_id: str,
        state_path=DEFAULT_STATE_PATH,
    ):
        self._sm = state_machine
        self._our_api_base_url = our_api_base_url.rstrip("/")
        self._api_key = api_key
        self._scenario_id = scenario_id
        self._state_path = state_path
        self._state: dict[str, Any] = load_state(state_path)
        self._device_meta: DeviceMeta = {}
        self._play_sent = False
        self._our_client: Optional[httpx.AsyncClient] = None

    def _save(self) -> None:
        save_state(self._state, self._state_path)

    async def _ensure_run(self) -> str:
        run_id = self._state.get("run_id")
        if run_id:
            logger.info("resuming persisted run %s", run_id)
            return run_id

        idempotency_key = self._state.get("run_create_idempotency_key") or str(uuid.uuid4())
        self._state["run_create_idempotency_key"] = idempotency_key
        run = await self._sm.create_run(self._scenario_id, idempotency_key)
        self._state["run_id"] = run["run_id"]
        self._state["generation"] = run["generation"]
        self._state.pop("cursor", None)
        self._save()
        logger.info("created run %s (scenario=%s)", run["run_id"], self._scenario_id)
        return run["run_id"]

    async def _maybe_play(self, run_id: str, run_status: str, generation: int) -> None:
        """Send `play` once per process lifetime, the first time we see the run paused
        (covers both a freshly created run and resuming after our own restart)."""
        if self._play_sent or run_status != "paused":
            return
        try:
            await self._sm.send_command(run_id, generation, "play")
            logger.info("sent play command (run=%s, generation=%s)", run_id, generation)
        except StateMachineError as exc:
            logger.warning("play command failed, continuing to consume the stream: %s", exc)
        self._play_sent = True

    async def _forward(self, telemetry_in: dict[str, Any]) -> None:
        assert self._our_client is not None
        response = await self._our_client.post("/ingest/telemetry", json=telemetry_in)
        if response.status_code >= 400:
            logger.warning(
                "our /ingest/telemetry rejected a mapped event (%s): %s",
                response.status_code,
                response.text[:300],
            )

    async def _run_once(self, run_id: str) -> bool:
        """Consume the stream until a clean reconnect point, an error, or the stream
        simply ending. Returns True when the exit is an intentional, immediate reconnect
        point (stream.reset / heartbeat generation bump: reconnect now, no backoff) and
        False when the underlying stream just ended without one of those signals (e.g. a
        network drop) -- an unexpected disconnect, which should back off before retrying.
        Raises StateMachineError/httpx.HTTPError to signal a real failure instead."""
        cursor = self._state.get("cursor")
        async for frame, data in self._sm.stream(run_id, cursor=cursor):
            if frame == "snapshot":
                apply_snapshot(self._device_meta, data)
                self._state["generation"] = data["run"]["generation"]
                self._state["cursor"] = data["as_of"]["cursor"]
                self._save()
                await self._maybe_play(run_id, data["run"]["status"], data["run"]["generation"])
                continue

            if frame == "heartbeat":
                # Heartbeats never advance the cursor; only note liveness, per contract.
                if data.get("generation") != self._state.get("generation"):
                    logger.info("heartbeat reports a new generation; reconnecting for a fresh snapshot")
                    clear_cursor(self._state)
                    self._save()
                    return True
                logger.debug(
                    "heartbeat: sim_time_ms=%s last_sequence=%s",
                    data.get("sim_time_ms"),
                    data.get("last_sequence"),
                )
                continue

            if frame == "event":
                if data.get("kind") == "stream.reset":
                    logger.info(
                        "stream.reset: generation %s -> %s; reconnecting for a fresh snapshot",
                        self._state.get("generation"),
                        data.get("generation"),
                    )
                    self._state["generation"] = data.get("generation")
                    clear_cursor(self._state)
                    self._play_sent = False
                    self._save()
                    return True

                mapped = map_event_to_telemetry_in(data, self._device_meta)
                if mapped is not None:
                    try:
                        await self._forward(mapped)
                    except httpx.HTTPError as exc:
                        logger.warning("failed to reach our own /ingest/telemetry: %s", exc)
                self._state["cursor"] = data.get("cursor", self._state.get("cursor"))
                self._save()
                continue

            logger.debug("ignoring unrecognized SSE frame: %s", frame)

        # The stream ended without an explicit stream.reset/heartbeat-generation-bump
        # signal (e.g. the connection was simply dropped) -- treat as an unexpected
        # disconnect so the caller backs off before reconnecting.
        return False

    async def run_forever(self) -> None:
        headers = {"X-API-Key": self._api_key}
        async with httpx.AsyncClient(
            base_url=self._our_api_base_url, timeout=10.0, headers=headers
        ) as our_client:
            self._our_client = our_client

            try:
                run_id = await self._ensure_run()
            except FatalAuthError as exc:
                logger.error(
                    "authentication failed while creating/resuming the run (%s) -- not retrying. "
                    "Check STATE_MACHINE_BEARER_TOKEN.",
                    exc,
                )
                return
            except StateMachineError as exc:
                logger.error("failed to create/resume run: %s", exc)
                return
            except httpx.HTTPError as exc:
                logger.error("failed to reach the State Machine API to create/resume run: %s", exc)
                return

            attempt = 0
            while True:
                try:
                    clean_reconnect = await self._run_once(run_id)
                except FatalAuthError as exc:
                    logger.error(
                        "authentication failed (%s) -- not retrying. Check STATE_MACHINE_BEARER_TOKEN.",
                        exc,
                    )
                    return
                except StateMachineError as exc:
                    if exc.code == "CURSOR_EXPIRED":
                        logger.warning("cursor expired; reconnecting without cursor for a fresh snapshot")
                        clear_cursor(self._state)
                        self._save()
                        attempt = 0
                        continue
                    if exc.code == "RUN_EXPIRED":
                        logger.error(
                            "run %s expired; the contract requires explicit user action to start a "
                            "new one (not auto-created). Delete %s to start fresh.",
                            run_id,
                            self._state_path,
                        )
                        return
                    logger.warning("stream error (%s), reconnecting with backoff: %s", exc.code, exc)
                except httpx.HTTPError as exc:
                    logger.warning("transport error, reconnecting with backoff: %s", exc)
                else:
                    if clean_reconnect:
                        attempt = 0
                        continue  # intentional reconnect point (stream.reset / heartbeat bump); no backoff
                    logger.warning("stream ended unexpectedly; reconnecting with backoff")

                delay = RECONNECT_DELAYS_S[min(attempt, len(RECONNECT_DELAYS_S) - 1)]
                delay += random.uniform(0, delay * 0.2)
                logger.info("reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                attempt += 1


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not settings.state_machine_bearer_token:
        logger.error(
            "STATE_MACHINE_BEARER_TOKEN is not set. Put it in your own .env, sourced from "
            "1Password (vault aitinkerers-hack, item 'State Machine API'); never hardcode it."
        )
        return

    client = StateMachineClient(settings.state_machine_base_url, settings.state_machine_bearer_token)
    bridge = Bridge(
        state_machine=client,
        our_api_base_url=settings.our_api_base_url,
        api_key=settings.api_key,
        scenario_id=settings.state_machine_scenario_id,
    )
    logger.info(
        "starting State Machine bridge: base_url=%s scenario_id=%s -> %s",
        settings.state_machine_base_url,
        settings.state_machine_scenario_id,
        settings.our_api_base_url,
    )
    await bridge.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
