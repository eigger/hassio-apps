"""Client for the ESPHome Device Builder dashboard API.

Speaks the same documented WebSocket protocol the dashboard frontend uses
(``docs/API.md`` in esphome/device-builder), so a firmware build here is the
exact same operation as clicking Install in the dashboard:

    firmware/compile        -> queue a build
    firmware/follow_job     -> stream it to completion
    firmware/get_binaries   -> list artifacts already on disk
    firmware/download_token -> mint a single-use token
    GET /api/firmware/download?token=...  -> the bytes
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Callable

import aiohttp

LOG = logging.getLogger("dashboard")

OTA_FILE = "firmware.ota.bin"

# A compile of a fresh ESP-IDF config on a slow host really can take this long.
COMPILE_TIMEOUT = 45 * 60
COMMAND_TIMEOUT = 60


class DashboardError(RuntimeError):
    """The dashboard refused a command or could not be reached."""


class DashboardClient:
    """One WebSocket session against the dashboard.

    Use as an async context manager. Commands are multiplexed by
    ``message_id``; a single reader task fans replies out to per-message
    queues so a long-running ``follow_job`` stream doesn't block anything else.
    """

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.server_info: dict[str, Any] = {}
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._next_id = 0

    # -- lifecycle ---------------------------------------------------------

    async def __aenter__(self) -> "DashboardClient":
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self._session = aiohttp.ClientSession(headers=headers)
        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        try:
            self._ws = await self._session.ws_connect(f"{ws_url}/ws", heartbeat=30)
        except Exception as err:  # noqa: BLE001
            await self._session.close()
            raise DashboardError(f"Cannot reach the ESPHome dashboard at {self.base_url}: {err}") from err

        self._reader = asyncio.create_task(self._read_loop())
        self.server_info = await self._await_server_info()

        if self.server_info.get("requires_auth"):
            if not self.token:
                raise DashboardError(
                    "The ESPHome dashboard requires authentication. Set 'dashboard_token' "
                    "in the add-on options, or reach the dashboard over its ingress port."
                )
            await self.command("auth/login", {"token": self.token})
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def _await_server_info(self) -> dict[str, Any]:
        queue = self._queues.setdefault("", asyncio.Queue())
        try:
            return await asyncio.wait_for(queue.get(), timeout=20)
        except asyncio.TimeoutError as err:
            raise DashboardError("The dashboard never sent its server info") from err

    async def _read_loop(self) -> None:
        assert self._ws is not None
        async for msg in self._ws:
            if msg.type is not aiohttp.WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except ValueError:
                LOG.debug("Ignoring non-JSON frame")
                continue
            # The unsolicited handshake frame carries no message_id.
            key = payload.get("message_id", "")
            self._queues.setdefault(key, asyncio.Queue()).put_nowait(payload)

    # -- protocol ----------------------------------------------------------

    async def command(self, command: str, args: dict[str, Any] | None = None) -> Any:
        """Send a command and return its result."""
        message_id, queue = self._begin(command, args)
        try:
            payload = await asyncio.wait_for(queue.get(), timeout=COMMAND_TIMEOUT)
        except asyncio.TimeoutError as err:
            raise DashboardError(f"Timed out waiting for '{command}'") from err
        finally:
            self._queues.pop(message_id, None)
        return self._unwrap(command, payload)

    async def stream(self, command: str, args: dict[str, Any] | None = None,
                     timeout: float = COMPILE_TIMEOUT) -> AsyncIterator[dict[str, Any]]:
        """Send a streaming command, yielding every frame until it terminates."""
        message_id, queue = self._begin(command, args)
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise DashboardError(f"Timed out streaming '{command}'")
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError as err:
                    raise DashboardError(f"Timed out streaming '{command}'") from err

                if "error_code" in payload:
                    raise DashboardError(
                        f"{command} failed: {payload['error_code']} {payload.get('details', '')}".strip()
                    )
                yield payload
                if payload.get("event") == "result" or "result" in payload:
                    return
        finally:
            self._queues.pop(message_id, None)

    def _begin(self, command: str, args: dict[str, Any] | None) -> tuple[str, asyncio.Queue]:
        if self._ws is None or self._ws.closed:
            raise DashboardError("The dashboard connection is closed")
        self._next_id += 1
        message_id = str(self._next_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[message_id] = queue
        frame = {"command": command, "message_id": message_id, "args": args or {}}
        asyncio.ensure_future(self._ws.send_str(json.dumps(frame)))
        return message_id, queue

    @staticmethod
    def _unwrap(command: str, payload: dict[str, Any]) -> Any:
        if "error_code" in payload:
            raise DashboardError(
                f"{command} failed: {payload['error_code']} {payload.get('details', '')}".strip()
            )
        return payload.get("result")

    # -- operations --------------------------------------------------------

    async def devices(self) -> list[dict[str, Any]]:
        result = await self.command("devices/list") or {}
        return result.get("configured", []) if isinstance(result, dict) else list(result)

    async def binaries(self, configuration: str) -> list[dict[str, Any]]:
        return await self.command("firmware/get_binaries", {"configuration": configuration}) or []

    async def has_ota_binary(self, configuration: str) -> bool:
        return any(b.get("file") == OTA_FILE for b in await self.binaries(configuration))

    async def compile(self, configuration: str, on_output: Callable[[str], None] | None = None) -> None:
        """Queue a compile and block until it finishes. Raises on failure."""
        job = await self.command("firmware/compile", {"configuration": configuration})
        job_id = (job or {}).get("job_id")
        if not job_id:
            raise DashboardError(f"The dashboard did not return a job id for {configuration}")

        status = "unknown"
        async for frame in self.stream("firmware/follow_job", {"job_id": job_id}):
            event = frame.get("event")
            data = frame.get("data")
            if event == "output" and on_output and isinstance(data, str):
                on_output(data.rstrip("\n"))
            elif event == "result" and isinstance(data, dict):
                status = data.get("status", status)
            elif isinstance(data, dict) and "status" in data:
                status = data["status"]

        if status not in ("completed", "unknown"):
            raise DashboardError(f"Build of {configuration} ended as '{status}'")

    async def download_ota(self, configuration: str) -> bytes:
        """Fetch firmware.ota.bin for a configuration."""
        minted = await self.command(
            "firmware/download_token", {"configuration": configuration, "file": OTA_FILE}
        )
        token = (minted or {}).get("token")
        if not token:
            raise DashboardError(f"No download token issued for {configuration}")

        assert self._session is not None
        url = f"{self.base_url}/api/firmware/download"
        async with self._session.get(url, params={"token": token}) as resp:
            if resp.status != 200:
                raise DashboardError(
                    f"Download of {OTA_FILE} for {configuration} returned HTTP {resp.status}"
                )
            return await resp.read()
