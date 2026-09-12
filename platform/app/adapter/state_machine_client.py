"""Async client for the simulator team's State Machine API: run lifecycle (create run,
send commands) plus a spec-compliant SSE stream reader.

Source contract: raw-source/fire-safety-state-api-v0.2.2/.../v0.2/README.md section 6
("SSE: начальный снимок, события, переподключение") and CONNECTION.md. Uses `httpx-sse`
for framing rather than a hand-rolled `for line in response`/`json.loads` loop: the
contract explicitly warns against parsing once per TCP chunk (a chunk can split a UTF-8
character, contain several SSE messages, or end mid-line) -- httpx-sse's decoder buffers
correctly across chunk boundaries and joins multi-line `data:` fields per the WHATWG SSE
spec, LF/CR/CRLF included.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, AsyncIterator, Optional

import httpx
from httpx_sse import aconnect_sse

logger = logging.getLogger(__name__)

# Reconnect backoff per README section 6: "паузы 1, 2, 4, 8, 15 секунд с небольшим jitter".
RECONNECT_DELAYS_S: list[float] = [1, 2, 4, 8, 15]


class StateMachineError(Exception):
    """Raised for any `Error` object the API returns, whether as an HTTP error response
    or a mid-stream `stream_error` SSE frame."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int = 0,
        retryable: bool = False,
        details: Optional[dict[str, Any]] = None,
    ):
        super().__init__(f"{code} ({http_status}): {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.details = details or {}


class FatalAuthError(StateMachineError):
    """401/403 -- per contract, "не повторять бесконечно" (don't retry forever)."""


def _error_from_response(response: httpx.Response) -> StateMachineError:
    try:
        body = response.json()
        error = body.get("error", body)
    except ValueError:
        error = {}
    code = error.get("code", "UNKNOWN")
    message = error.get("message") or response.text[:200]
    retryable = bool(error.get("retryable", False))
    details = error.get("details") or {}
    cls = FatalAuthError if response.status_code in (401, 403) else StateMachineError
    return cls(code, message, response.status_code, retryable, details)


class StateMachineClient:
    def __init__(self, base_url: str, bearer_token: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {bearer_token}"}
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=self._timeout)

    async def create_run(
        self, scenario_id: str, idempotency_key: str, speed: int = 1
    ) -> dict[str, Any]:
        """POST /runs. Same Idempotency-Key + body returns the same run (201) -- safe to
        call again on every bridge startup with a persisted key."""
        async with self._client() as client:
            response = await client.post(
                "/runs",
                json={"scenario_id": scenario_id, "speed": speed},
                headers={"Idempotency-Key": idempotency_key},
            )
            if response.status_code >= 400:
                raise _error_from_response(response)
            return response.json()

    async def send_command(
        self, run_id: str, expected_generation: int, action: str, **extra_fields: Any
    ) -> dict[str, Any]:
        """POST /runs/{run_id}/commands with a fresh command_id (a new command_id is
        required for a new logical action; retries of a network timeout should reuse the
        same command_id+body, which callers of this method must do themselves)."""
        command_id = str(uuid.uuid4())
        body = {
            "command_id": command_id,
            "expected_generation": expected_generation,
            "action": action,
            **extra_fields,
        }
        async with self._client() as client:
            response = await client.post(f"/runs/{run_id}/commands", json=body)
            if response.status_code >= 400:
                raise _error_from_response(response)
            return response.json()

    async def stream(
        self, run_id: str, cursor: Optional[str] = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Open GET /runs/{run_id}/stream and yield (frame_name, parsed_json) for each
        `snapshot`/`event`/`heartbeat` frame. Raises StateMachineError on a non-2xx open
        (e.g. 410 CURSOR_EXPIRED, 401/403) or a mid-stream `stream_error` frame; the
        caller (bridge) decides how to react (reconnect with/without cursor, give up).

        Pass `cursor` (their opaque `Event.cursor` string) to resume via `Last-Event-ID`;
        omit it to receive a fresh `snapshot` frame.
        """
        headers = {"Last-Event-ID": cursor} if cursor else {}
        async with self._client() as client:
            async with aconnect_sse(client, "GET", f"/runs/{run_id}/stream", headers=headers) as event_source:
                response = event_source.response
                if response.status_code >= 400:
                    await response.aread()
                    raise _error_from_response(response)

                async for sse in event_source.aiter_sse():
                    if sse.event == "stream_error":
                        error = sse.json()
                        detail = error.get("error", error)
                        raise StateMachineError(
                            detail.get("code", "STREAM_ERROR"),
                            detail.get("message", ""),
                            0,
                            bool(detail.get("retryable", False)),
                            detail.get("details") or {},
                        )
                    if not sse.data:
                        continue
                    yield (sse.event or "message"), sse.json()
