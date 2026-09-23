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
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect

from .config import Settings
from .host_fs import atomic_write_text, restrict_to_owner

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
IDENTITY_VERSION = 1
HELLO_TIMEOUT_SECONDS = 10.0


class RelayError(RuntimeError):
    """A relay operation failed without exposing connector credentials."""


@dataclass(frozen=True)
class RelayIdentity:
    installation_id: str
    connector_secret: str


@dataclass(frozen=True)
class RelayIdentityState:
    version: int
    active: RelayIdentity
    fallback: RelayIdentity | None = None


def _parse_identity(value: object) -> RelayIdentity | None:
    if not isinstance(value, dict):
        return None
    installation_id = value.get("installation_id")
    connector_secret = value.get("connector_secret")
    if (
        not isinstance(installation_id, str)
        or not installation_id.strip()
        or not isinstance(connector_secret, str)
        or not connector_secret.strip()
    ):
        return None
    return RelayIdentity(installation_id.strip(), connector_secret.strip())


def load_relay_identity_state(data_dir: Path) -> RelayIdentityState | None:
    """Load the versioned identity, accepting the legacy single-identity format."""

    try:
        payload = json.loads(relay_identity_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") == IDENTITY_VERSION:
        active = _parse_identity(payload.get("active"))
        fallback = _parse_identity(payload.get("fallback"))
        return RelayIdentityState(IDENTITY_VERSION, active, fallback) if active else None
    legacy = _parse_identity(payload)
    return RelayIdentityState(IDENTITY_VERSION, legacy) if legacy else None


def _write_relay_identity_state(data_dir: Path, state: RelayIdentityState) -> None:
    payload: dict[str, object] = {
        "version": state.version,
        "active": state.active.__dict__,
        "fallback": state.fallback.__dict__ if state.fallback else None,
    }
    atomic_write_text(
        relay_identity_path(data_dir),
        json.dumps(payload, separators=(",", ":")) + "\n",
        before_replace=restrict_to_owner,
    )


def ensure_relay_identity(
    data_dir: Path, configured_id: str | None = None, configured_secret: str | None = None
) -> RelayIdentity:
    """Create a per-installation identity, stored with restrictive permissions."""

    if configured_id and configured_secret:
        return RelayIdentity(configured_id.strip(), configured_secret.strip())
    state = load_relay_identity_state(data_dir)
    if state is not None:
        return state.active
    identity = RelayIdentity(str(uuid4()), secrets.token_urlsafe(48))
    _write_relay_identity_state(data_dir, RelayIdentityState(IDENTITY_VERSION, identity))
    return identity


def relay_identity_path(data_dir: Path) -> Path:
    """Return the private file-backed connector identity location."""

    return data_dir / ".discord-relay-identity.json"


def persist_relay_identity(data_dir: Path, identity: RelayIdentity) -> None:
    """Stage an active identity with the prior credential as crash fallback."""

    current = load_relay_identity_state(data_dir)
    fallback: RelayIdentity | None = None
    if current is not None:
        if identity == current.active:
            fallback = current.fallback
        elif identity != current.fallback:
            fallback = current.active
    _write_relay_identity_state(
        data_dir, RelayIdentityState(IDENTITY_VERSION, identity, fallback)
    )


def finalize_relay_identity(data_dir: Path, identity: RelayIdentity) -> None:
    """Commit a credential after the relay has acknowledged its connector hello."""

    if relay_identity_path(data_dir).exists():
        _write_relay_identity_state(
            data_dir, RelayIdentityState(IDENTITY_VERSION, identity)
        )


def relay_url(settings: Settings) -> str | None:
    value = settings.discord_relay_url.strip() if settings.discord_relay_url else ""
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.port != 0
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise RelayError("BLOCKSTEAD_DISCORD_RELAY_URL must be an HTTPS relay origin")
    return value.rstrip("/")


def relay_configuration(settings: Settings) -> dict[str, object]:
    try:
        url = relay_url(settings)
        configuration_error: str | None = None
    except RelayError as exc:
        url = None
        configuration_error = str(exc)
    return {
        "configured": bool(url),
        "url": url,
        "relay_configured": bool(url),
        "relay_url": url,
        "relay_error": configuration_error,
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

    def replace_identity(self, identity: RelayIdentity) -> None:
        self.identity = identity

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

    def prepare_rotation(
        self, replacement_secret: str, ttl_seconds: int = 600
    ) -> dict[str, object]:
        return self._request(
            "POST",
            "/v1/installations/rotation/prepare",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
                "replacement_secret": replacement_secret,
                "ttl_seconds": ttl_seconds,
            },
        )

    def cancel_rotation(self) -> dict[str, object]:
        return self._request(
            "POST",
            "/v1/installations/rotation/cancel",
            json={
                "installation_id": self.identity.installation_id,
                "connector_secret": self.identity.connector_secret,
            },
        )

    def rotation_status(self) -> dict[str, object]:
        return self._request(
            "POST",
            "/v1/installations/rotation/status",
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

    async def replace_identity(self, identity: RelayIdentity) -> None:
        """Require an acknowledged replacement hello before switching locally."""

        await self._probe_identity(identity)
        was_running = self._task is not None and not self._task.done()
        await self.stop()
        self._identity = identity
        finalize_relay_identity(self._settings.data_dir, identity)
        if was_running:
            self.start()

    def _ssl(self) -> ssl.SSLContext | None:
        if not self._url.startswith("wss://"):
            return None
        context = ssl.create_default_context()
        if self._settings.discord_relay_ca_file is not None:
            context.load_verify_locations(cafile=str(self._settings.discord_relay_ca_file))
        return context

    def _identity_candidates(self) -> tuple[RelayIdentity, ...]:
        candidates = [self._identity]
        state = load_relay_identity_state(self._settings.data_dir)
        if (
            state is not None
            and state.active == self._identity
            and state.fallback is not None
            and state.fallback not in candidates
        ):
            candidates.append(state.fallback)
        return tuple(candidates)

    async def _hello(self, socket: Any, identity: RelayIdentity) -> dict[str, object]:
        await socket.send(
            json.dumps(
                {
                    "type": "hello",
                    "protocol_version": PROTOCOL_VERSION,
                    "installation_id": identity.installation_id,
                    "connector_secret": identity.connector_secret,
                }
            )
        )
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=HELLO_TIMEOUT_SECONDS)
            hello = json.loads(raw)
        except (TimeoutError, ValueError) as exc:
            raise RelayError("The relay did not acknowledge the host connector") from exc
        if (
            not isinstance(hello, dict)
            or hello.get("type") != "hello_ok"
            or hello.get("protocol_version") != PROTOCOL_VERSION
            or hello.get("installation_id") != identity.installation_id
        ):
            raise RelayError("The relay rejected the host connector")
        return hello

    async def _probe_identity(self, identity: RelayIdentity) -> None:
        try:
            async with connect(
                self._url,
                ssl=self._ssl(),
                max_size=2_000_000,
                ping_interval=20,
                ping_timeout=20,
            ) as socket:
                await self._hello(socket, identity)
        except RelayError:
            raise
        except Exception as exc:
            raise RelayError("The relay did not accept the replacement connector") from exc

    async def _session(self, identity: RelayIdentity) -> None:
        async with connect(
            self._url,
            ssl=self._ssl(),
            max_size=2_000_000,
            ping_interval=20,
            ping_timeout=20,
        ) as socket:
            self._socket = socket
            hello = await self._hello(socket, identity)
            self._identity = identity
            finalize_relay_identity(self._settings.data_dir, identity)
            self._connected = True
            self._last_connected_at = datetime_now_iso()
            await self._on_event(
                {
                    "type": "relay_connected",
                    "protocol_version": PROTOCOL_VERSION,
                    "installation_id": identity.installation_id,
                    "discord_ready": bool(hello.get("discord_ready")),
                    "heartbeat_healthy": bool(hello.get("heartbeat_healthy")),
                }
            )
            try:
                async for raw in socket:
                    message = json.loads(raw)
                    if isinstance(message, dict):
                        await self._on_event(message)
            finally:
                self._connected = False
                await self._on_event(
                    {
                        "type": "relay_disconnected",
                        "protocol_version": PROTOCOL_VERSION,
                        "installation_id": identity.installation_id,
                        "discord_ready": False,
                        "heartbeat_healthy": False,
                    }
                )

    async def run(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            connected = False
            for identity in self._identity_candidates():
                try:
                    await self._session(identity)
                    connected = True
                    delay = 2.0
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._connected = False
                    self._socket = None
            if self._stop.is_set():
                break
            self._connected = False
            self._socket = None
            if not connected:
                log.warning("Discord relay connector disconnected; retrying")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except TimeoutError:
                delay = min(60.0, delay * 2)

    def _binding(
        self,
        connection_id: str,
        profile_id: str,
        application_id: str,
        guild_id: str,
        channel_id: str,
    ) -> dict[str, object]:
        values = (connection_id, profile_id, application_id, guild_id, channel_id)
        if not all(isinstance(value, str) and value for value in values):
            raise RelayError("The relay connection binding is incomplete")
        return {
            "protocol_version": PROTOCOL_VERSION,
            "installation_id": self._identity.installation_id,
            "connection_id": connection_id,
            "profile_id": profile_id,
            "application_id": application_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
        }

    async def send_status(
        self,
        connection_id: str,
        sequence: int,
        snapshot: dict[str, object],
        *,
        profile_id: str,
        application_id: str,
        guild_id: str,
        channel_id: str,
    ) -> None:
        await self._send(
            {
                "type": "status",
                **self._binding(
                    connection_id, profile_id, application_id, guild_id, channel_id
                ),
                "sequence": sequence,
                "snapshot": snapshot,
            }
        )

    async def send_heartbeat(
        self,
        connection_id: str,
        *,
        profile_id: str,
        application_id: str,
        guild_id: str,
        channel_id: str,
    ) -> None:
        await self._send(
            {
                "type": "heartbeat",
                **self._binding(
                    connection_id, profile_id, application_id, guild_id, channel_id
                ),
            }
        )

    async def send_profile_binding_unavailable(
        self,
        connection_id: str,
        profile_id: str,
        *,
        application_id: str,
        guild_id: str,
        channel_id: str,
        reason: str = "profile_unavailable",
    ) -> None:
        await self._send(
            {
                "type": "profile_binding_unavailable",
                **self._binding(
                    connection_id, profile_id, application_id, guild_id, channel_id
                ),
                "reason": reason[:64],
            }
        )

    async def send_profile_binding(
        self,
        connection_id: str,
        profile_id: str,
        *,
        application_id: str,
        guild_id: str,
        channel_id: str,
        enabled: bool = True,
    ) -> None:
        await self._send(
            {
                "type": "profile_binding",
                **self._binding(
                    connection_id, profile_id, application_id, guild_id, channel_id
                ),
                "enabled": enabled,
                "available": True,
            }
        )

    async def _send(self, message: dict[str, object]) -> None:
        if not self._connected or self._socket is None:
            return
        async with self._send_lock:
            await self._socket.send(json.dumps(message))


def datetime_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
