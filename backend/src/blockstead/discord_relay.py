"""Outbound Blockstead connector for the central Discord relay."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from .config import Settings

log = logging.getLogger(__name__)


class RelayError(RuntimeError):
    """A relay operation failed without exposing connector credentials."""


@dataclass(frozen=True)
class RelayIdentity:
    installation_id: str
    connector_secret: str


def ensure_relay_identity(
    data_dir: Path, configured_id: str | None = None, configured_secret: str | None = None
) -> RelayIdentity:
    """Create a per-installation identity, stored with restrictive permissions."""

    identity_path = data_dir / ".discord-relay-identity.json"
    if configured_id and configured_secret:
        return RelayIdentity(configured_id.strip(), configured_secret.strip())
    try:
        payload = json.loads(identity_path.read_text(encoding="utf-8"))
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("installation_id"), str)
            and isinstance(payload.get("connector_secret"), str)
        ):
            return RelayIdentity(payload["installation_id"], payload["connector_secret"])
    except (OSError, ValueError):
        pass
    identity = RelayIdentity(str(uuid4()), secrets.token_urlsafe(48))
    identity_path.write_text(json.dumps(identity.__dict__) + "\n", encoding="utf-8")
    identity_path.chmod(0o600)
    return identity


def relay_url(settings: Settings) -> str | None:
    value = settings.discord_relay_url.strip() if settings.discord_relay_url else ""
    if not value:
        return None
    if not value.startswith(("https://", "http://")):
        raise RelayError("BLOCKSTEAD_DISCORD_RELAY_URL must use http:// or https://")
    return value.rstrip("/")


def relay_configuration(settings: Settings) -> dict[str, object]:
    url = relay_url(settings)
    return {
        "configured": bool(url),
        "url": url,
        "installation_id": settings.discord_relay_installation_id,
        "connector_configured": bool(settings.discord_relay_connector_secret),
        "mode": "central_relay" if url else "not_configured",
    }


class RelayClient:
    """Synchronous control-plane client used by dashboard request handlers."""

    def __init__(self, settings: Settings, identity: RelayIdentity) -> None:
        base = relay_url(settings)
        if base is None:
            raise RelayError("The Discord relay URL is not configured")
        verify: bool | str = True
        if settings.discord_relay_ca_file is not None:
            verify = str(settings.discord_relay_ca_file)
        self.identity = identity
        self._client = httpx.Client(base_url=base, timeout=10.0, verify=verify)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, object]:
        try:
            response = self._client.request(method, path, **kwargs)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RelayError("The Discord relay did not accept the request") from exc
        if not isinstance(body, dict):
            raise RelayError("The Discord relay returned an invalid response")
        return body

    def register_pairing(self, profile_id: str, profile_name: str, code: str) -> dict[str, object]:
        return self._request(
            "POST",
            "/v1/pairings/register",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
                "profile_id": profile_id,
                "profile_name": profile_name,
                "code": code,
            },
        )

    def register_installation(self) -> None:
        self._request(
            "POST",
            "/v1/installations/register",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
            },
        )

    def confirm_pairing(self, pairing_id: str) -> dict[str, object]:
        return self._request(
            "POST",
            f"/v1/pairings/{pairing_id}/confirm",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
            },
        )

    def update_connection(self, connection_id: str, **changes: object) -> dict[str, object]:
        return self._request(
            "PATCH",
            f"/v1/connections/{connection_id}",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
                **changes,
            },
        )

    def revoke_connection(self, connection_id: str) -> dict[str, object]:
        return self._request(
            "DELETE",
            f"/v1/connections/{connection_id}",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
            },
        )


class RelayConnector:
    """Reconnectable outbound WebSocket carrying only scoped status data."""

    def __init__(
        self,
        settings: Settings,
        identity: RelayIdentity,
        on_event: Callable[[Mapping[str, object]], Awaitable[None]],
    ) -> None:
        base = relay_url(settings)
        if base is None:
            raise RelayError("The Discord relay URL is not configured")
        self._url = (
            base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/v1/connect"
        )
        self._settings = settings
        self._identity = identity
        self._on_event = on_event
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._socket: Any = None
        self._send_lock = asyncio.Lock()
        self._connected = False
        self._last_connected_at: str | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_connected_at(self) -> str | None:
        return self._last_connected_at

    def start(self) -> asyncio.Task[None]:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self.run())
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            await self._socket.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._connected = False

    def _ssl(self) -> ssl.SSLContext | None:
        if not self._url.startswith("wss://"):
            return None
        context = ssl.create_default_context()
        if self._settings.discord_relay_ca_file is not None:
            context.load_verify_locations(cafile=str(self._settings.discord_relay_ca_file))
        return context

    async def run(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            try:
                async with connect(
                    self._url,
                    ssl=self._ssl(),
                    max_size=2_000_000,
                    ping_interval=20,
                    ping_timeout=20,
                ) as socket:
                    self._socket = socket
                    await socket.send(
                        json.dumps(
                            {
                                "type": "hello",
                                "installation_id": self._identity.installation_id,
                                "connector_secret": self._identity.connector_secret,
                            }
                        )
                    )
                    hello = json.loads(await socket.recv())
                    if not isinstance(hello, dict) or hello.get("type") != "hello_ok":
                        raise RelayError("The relay rejected the host connector")
                    self._connected = True
                    self._last_connected_at = datetime_now_iso()
                    await self._on_event({"type": "relay_connected"})
                    async for raw in socket:
                        message = json.loads(raw)
                        if isinstance(message, dict):
                            await self._on_event(message)
                self._connected = False
                delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._connected = False
                log.warning("Discord relay connector disconnected; retrying")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    delay = min(60.0, delay * 2)

    async def send_status(
        self, connection_id: str, sequence: int, snapshot: dict[str, object]
    ) -> None:
        await self._send(
            {
                "type": "status",
                "connection_id": connection_id,
                "sequence": sequence,
                "snapshot": snapshot,
            }
        )

    async def send_heartbeat(self, connection_id: str) -> None:
        await self._send({"type": "heartbeat", "connection_id": connection_id})

    async def _send(self, message: dict[str, object]) -> None:
        if not self._connected or self._socket is None:
            return
        async with self._send_lock:
            await self._socket.send(json.dumps(message))


def datetime_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
