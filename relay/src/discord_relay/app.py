from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator

from .config import RelaySettings
from .discord import DiscordError, DiscordGateway
from .protocol import PROTOCOL_VERSION, RelayInteraction, RelayReply
from .store import Connection, Pairing, RelayStore, normalize_snowflake_ids

log = logging.getLogger("discord_relay")


class PairingRegister(BaseModel):
    installation_id: str = Field(min_length=8, max_length=128)
    connector_secret: str = Field(min_length=32, max_length=256)
    profile_id: str = Field(min_length=1, max_length=128)
    profile_name: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=8, max_length=32)


class InstallationRegister(BaseModel):
    installation_id: str = Field(min_length=8, max_length=128)
    connector_secret: str = Field(min_length=32, max_length=256)


class PairingConfirm(BaseModel):
    installation_id: str
    connector_secret: str


class ConnectionChange(BaseModel):
    installation_id: str
    connector_secret: str
    enabled: bool | None = None
    share_address: bool | None = None
    publish_address: bool | None = None
    authorized_user_ids: list[str] | None = Field(default=None, max_length=64)
    authorized_role_ids: list[str] | None = Field(default=None, max_length=64)

    @field_validator("authorized_user_ids", "authorized_role_ids")
    @classmethod
    def principal_ids_are_bounded_snowflakes(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return list(normalize_snowflake_ids(value))


class RotationPrepare(BaseModel):
    installation_id: str
    connector_secret: str
    replacement_secret: str = Field(min_length=32, max_length=256, repr=False)
    ttl_seconds: int = Field(default=600, ge=1, le=86_400)


class RotationControl(BaseModel):
    installation_id: str
    connector_secret: str = Field(repr=False)


SNAPSHOT_STATES = {
    "starting",
    "running",
    "stopping",
    "stopped",
    "crashed",
    "degraded",
    "unknown",
    "unavailable",
}
ADDRESS_STATES = {"unavailable", "local_only", "port_unverified"}


def _canonical_address(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise ValueError("snapshot address is invalid")
    host: str
    raw_port: str
    if value.startswith("["):
        end = value.find("]")
        if end < 0 or end + 1 >= len(value) or value[end + 1] != ":":
            raise ValueError("snapshot address is invalid")
        host, raw_port = value[1:end], value[end + 2 :]
    else:
        try:
            host, raw_port = value.rsplit(":", 1)
        except ValueError as exc:
            raise ValueError("snapshot address is invalid") from exc
    try:
        address = ipaddress.ip_address(host)
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("snapshot address is invalid") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("snapshot address is invalid")
    canonical_host = f"[{address}]" if address.version == 6 else str(address)
    canonical = f"{canonical_host}:{port}"
    if value != canonical:
        raise ValueError("snapshot address is not canonical")
    return canonical


def bounded_snapshot(snapshot: dict[str, Any], *, share_address: bool) -> dict[str, object]:
    """Validate and normalize the strict v1 public status snapshot."""

    required = {"protocol_version", "state", "players", "public", "host_observed_at"}
    if set(snapshot) != required or snapshot.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("snapshot v1 fields are invalid")
    state = snapshot.get("state")
    if not isinstance(state, str) or state not in SNAPSHOT_STATES:
        raise ValueError("snapshot state is invalid")
    players = snapshot.get("players")
    if not isinstance(players, dict) or set(players) != {"online", "max"}:
        raise ValueError("snapshot players are invalid")
    online = players.get("online")
    maximum = players.get("max")
    if (online is None) != (maximum is None):
        raise ValueError("snapshot players are incomplete")
    if online is not None and (
        not isinstance(online, int)
        or isinstance(online, bool)
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or online < 0
        or maximum < 0
        or online > maximum
        or maximum > 1_000_000
    ):
        raise ValueError("snapshot players are out of bounds")
    public = snapshot.get("public")
    if not isinstance(public, dict) or not {"state"} <= set(public) or set(public) - {
        "state",
        "address",
    }:
        raise ValueError("snapshot public state is invalid")
    address_state = public.get("state")
    if not isinstance(address_state, str) or address_state not in ADDRESS_STATES:
        raise ValueError("snapshot public state is invalid")
    address = public.get("address")
    if "address" in public and not share_address:
        raise ValueError("snapshot address sharing is disabled")
    normalized_public: dict[str, object] = {"state": address_state}
    if address is not None:
        normalized_public["address"] = _canonical_address(address)
    elif "address" in public:
        raise ValueError("snapshot address is invalid")
    observed = snapshot.get("host_observed_at")
    if not isinstance(observed, str):
        raise ValueError("snapshot observation time is invalid")
    try:
        observed_at = datetime.fromisoformat(observed)
    except ValueError as exc:
        raise ValueError("snapshot observation time is invalid") from exc
    if observed_at.tzinfo is None:
        raise ValueError("snapshot observation time is invalid")
    return {
        "protocol_version": PROTOCOL_VERSION,
        "state": state,
        "players": {"online": online, "max": maximum},
        "public": normalized_public,
        "host_observed_at": observed_at.astimezone(UTC).isoformat(),
    }


def pairing_payload(pairing: Pairing) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": pairing.id,
        "installation_id": pairing.installation_id,
        "profile_id": pairing.profile_id,
        "profile_name": pairing.profile_name,
        "status": pairing.status,
        "expires_at": pairing.expires_at.isoformat(),
        "claimed_application_id": pairing.claimed_application_id,
        "claimed_guild_id": pairing.claimed_guild_id,
        "claimed_channel_id": pairing.claimed_channel_id,
        "claimed_user_id": pairing.claimed_user_id,
        "claimed_role_ids": list(pairing.claimed_role_ids),
        "claimed_at": pairing.claimed_at.isoformat() if pairing.claimed_at else None,
        "confirmed_at": pairing.confirmed_at.isoformat() if pairing.confirmed_at else None,
    }


def connection_payload(connection: Connection, *, stale: bool = False) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "id": connection.id,
        "connection_id": connection.id,
        "installation_id": connection.installation_id,
        "profile_id": connection.profile_id,
        "profile_name": connection.profile_name,
        "application_id": connection.application_id,
        "guild_id": connection.guild_id,
        "channel_id": connection.channel_id,
        "owner_user_id": connection.owner_user_id,
        "authorized_user_ids": list(connection.authorized_user_ids),
        "authorized_role_ids": list(connection.authorized_role_ids),
        "enabled": connection.enabled,
        "share_address": connection.share_address,
        "publish_address": connection.publish_address,
        "status_message_id": connection.status_message_id,
        "last_sequence": connection.last_sequence,
        "last_heartbeat_at": connection.last_heartbeat_at.isoformat()
        if connection.last_heartbeat_at
        else None,
        "last_delivery_result": connection.last_delivery_result,
        "last_delivery_at": connection.last_delivery_at.isoformat()
        if connection.last_delivery_at
        else None,
        "last_delivery_detail": connection.last_delivery_detail,
        "revoked_at": connection.revoked_at.isoformat() if connection.revoked_at else None,
        "stale": stale,
    }


def binding_payload(connection: Connection) -> dict[str, object]:
    """Return the complete immutable routing envelope for one connection."""

    return {
        "protocol_version": PROTOCOL_VERSION,
        "installation_id": connection.installation_id,
        "connection_id": connection.id,
        "profile_id": connection.profile_id,
        "application_id": connection.application_id,
        "guild_id": connection.guild_id,
        "channel_id": connection.channel_id,
    }


def render_status(connection: Connection, snapshot: dict[str, Any] | None) -> str:
    if snapshot is None:
        return f"**Blockstead · {connection.profile_name}**\n⚪ Status: **Waiting for the host**"
    stale = bool(snapshot.get("stale"))
    state = str(snapshot.get("state", "unknown")).title()
    icon = "🟡" if stale else ("🟢" if state.lower() in {"running", "online"} else "🔴")
    players = snapshot.get("players") if isinstance(snapshot.get("players"), dict) else {}
    online = players.get("online") if isinstance(players, dict) else None
    maximum = players.get("max") if isinstance(players, dict) else None
    count = f"{online}/{maximum}" if online is not None and maximum is not None else "unavailable"
    lines = [
        f"**Blockstead · {connection.profile_name}**",
        f"{icon} Status: **{state}**",
        f"Players: **{count}**",
    ]
    if stale:
        lines.append("Last host update is stale; the host may be offline.")
    if connection.publish_address:
        public = snapshot.get("public") if isinstance(snapshot.get("public"), dict) else {}
        address = public.get("address") if isinstance(public, dict) else None
        lines.append(f"Join address: `{address}`" if address else "Join address: unavailable")
    lines.append("Use `/blockstead help` for available commands.")
    return "\n".join(lines)


class RelayRuntime:
    refresh_cooldown_seconds = 15
    max_refresh_entries = 10_000
    interaction_cooldown_seconds = 2
    max_interaction_entries = 10_000
    pair_attempt_window_seconds = 60
    pair_attempt_limit = 5
    max_pair_attempt_entries = 10_000
    delivery_attempts = 5
    generic_denial = "That Blockstead connection is not available."

    _AUDIT_DETAILS = {
        "accepted": "Command accepted.",
        "denied": "Command denied.",
        "failed": "Command failed safely.",
        "rate_limited": "Command rate limited.",
    }

    def __init__(self, settings: RelaySettings) -> None:
        self.settings = settings
        self.store = RelayStore(settings.database_path)
        self.gateway: DiscordGateway | None = None
        self.hosts: dict[str, WebSocket] = {}
        self.host_lock = asyncio.Lock()
        self.refreshes: OrderedDict[tuple[str, str], datetime] = OrderedDict()
        self.interaction_limits: OrderedDict[tuple[str, str, str], datetime] = OrderedDict()
        self.pair_attempts: OrderedDict[tuple[str, str, str, str], list[datetime]] = OrderedDict()
        self.delivery_desired: dict[str, tuple[str, str]] = {}
        self.delivery_attempted_hashes: dict[str, str] = {}
        self.delivery_tasks: dict[str, asyncio.Task[None]] = {}
        self.delivery_changes: dict[str, asyncio.Event] = {}
        self.delivery_scan_task: asyncio.Task[None] | None = None

    async def send_host(self, installation_id: str, message: dict[str, object]) -> bool:
        async with self.host_lock:
            socket = self.hosts.get(installation_id)
            if socket is None:
                return False
            try:
                await socket.send_json(message)
                return True
            except Exception:
                self.hosts.pop(installation_id, None)
                return False

    async def close_host(self, installation_id: str) -> None:
        async with self.host_lock:
            socket = self.hosts.pop(installation_id, None)
            if socket is not None:
                try:
                    await socket.close(code=1012, reason="connector rotation")
                except TypeError:
                    await socket.close()
                except Exception:
                    log.debug("Host socket was already closed during connector rotation")

    async def gateway_readiness(self, ready: bool, heartbeat_healthy: bool) -> None:
        async with self.host_lock:
            installation_ids = list(self.hosts)
        await asyncio.gather(
            *(
                self.send_host(
                    installation_id,
                    {
                        "type": "relay_readiness",
                        "protocol_version": PROTOCOL_VERSION,
                        "installation_id": installation_id,
                        "discord_ready": ready,
                        "heartbeat_healthy": heartbeat_healthy,
                    },
                )
                for installation_id in installation_ids
            )
        )

    async def _delivery_event(
        self, connection: Connection, result: str, *, desired_hash: str | None = None
    ) -> None:
        timestamp = datetime.now(UTC).isoformat()
        if result in {"delivered", "failed"}:
            updated = self.store.record_delivery(
                connection.id,
                result == "delivered",
                desired_hash=desired_hash if result == "delivered" else None,
            )
            if updated is not None:
                connection = updated
                timestamp = (
                    updated.last_delivery_at.isoformat()
                    if updated.last_delivery_at
                    else timestamp
                )
        detail = {
            "retrying": "Status message delivery is retrying.",
            "delivered": "Status message delivered.",
            "failed": "Status message delivery failed.",
        }[result]
        await self.send_host(
            connection.installation_id,
            {
                "type": "connection_delivery",
                **binding_payload(connection),
                "status_message_id": connection.status_message_id,
                "result": result,
                "outcome": result,
                "detail": detail,
                "delivered_at": timestamp,
                "timestamp": timestamp,
            },
        )

    async def _wait_for_retry(self, connection_id: str, delay: float) -> bool:
        changed = self.delivery_changes.setdefault(connection_id, asyncio.Event())
        try:
            await asyncio.wait_for(changed.wait(), timeout=delay)
        except TimeoutError:
            return False
        return True

    async def _deliver_with_retries(
        self, connection: Connection, content: str, desired_hash: str
    ) -> str:
        recreate_missing = False
        for attempt in range(self.delivery_attempts):
            current = self.store.connection(connection.id)
            if current is None or not current.enabled:
                return "failed"
            connection = current
            try:
                assert self.gateway is not None
                if connection.status_message_id and not recreate_missing:
                    try:
                        await self.gateway.rest.edit_message(
                            connection.channel_id, connection.status_message_id, content
                        )
                    except DiscordError as exc:
                        if exc.status_code != 404:
                            raise
                        recreate_missing = True
                        message_id = await self.gateway.rest.create_message(
                            connection.channel_id, content
                        )
                        self.store.set_status_message(connection.id, message_id)
                        refreshed = self.store.connection(connection.id)
                        if refreshed is not None:
                            connection = refreshed
                else:
                    message_id = await self.gateway.rest.create_message(
                        connection.channel_id, content
                    )
                    self.store.set_status_message(connection.id, message_id)
                    refreshed = self.store.connection(connection.id)
                    if refreshed is not None:
                        connection = refreshed
                await self._delivery_event(
                    connection, "delivered", desired_hash=desired_hash
                )
                return "delivered"
            except DiscordError as exc:
                latest = self.delivery_desired.get(connection.id)
                if latest is None or latest[0] != desired_hash:
                    return "superseded"
                terminal = not exc.retryable or attempt == self.delivery_attempts - 1
                if terminal:
                    await self._delivery_event(connection, "failed")
                    return "failed"
                await self._delivery_event(connection, "retrying")
                delay = exc.retry_after if exc.retry_after is not None else float(2**attempt)
                if await self._wait_for_retry(connection.id, delay):
                    return "superseded"
            except Exception:
                log.warning("Could not publish one Blockstead status message")
                await self._delivery_event(connection, "failed")
                return "failed"
        return "failed"

    async def _delivery_worker(self, connection_id: str) -> None:
        try:
            while True:
                desired = self.delivery_desired.get(connection_id)
                if desired is None:
                    return
                desired_hash, content = desired
                self.delivery_changes.setdefault(connection_id, asyncio.Event()).clear()
                connection = self.store.connection(connection_id)
                if connection is None or not connection.enabled:
                    return
                if connection.last_delivered_hash == desired_hash:
                    self.delivery_attempted_hashes[connection_id] = desired_hash
                    return
                if self.delivery_attempted_hashes.get(connection_id) == desired_hash:
                    return
                outcome = await self._deliver_with_retries(
                    connection, content, desired_hash
                )
                if outcome != "superseded":
                    self.delivery_attempted_hashes[connection_id] = desired_hash
                latest = self.delivery_desired.get(connection_id)
                if latest is None or latest[0] == desired_hash:
                    return
        finally:
            self.delivery_tasks.pop(connection_id, None)

    async def publish(self, connection: Connection) -> None:
        snapshot = self.store.snapshot(connection, self.settings.stale_after_seconds)
        content = render_status(connection, snapshot)
        desired_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        self.delivery_desired[connection.id] = (desired_hash, content)
        self.delivery_changes.setdefault(connection.id, asyncio.Event()).set()
        task = self.delivery_tasks.get(connection.id)
        if task is None or task.done():
            task = asyncio.create_task(self._delivery_worker(connection.id))
            self.delivery_tasks[connection.id] = task
        await asyncio.shield(task)

    async def reconcile_deliveries(self) -> None:
        await asyncio.gather(
            *(
                self.publish(connection)
                for connection in self.store.active_connections()
                if connection.enabled
            )
        )

    async def delivery_scan_loop(self) -> None:
        interval = min(30.0, max(1.0, self.settings.stale_after_seconds / 4))
        while True:
            await asyncio.sleep(interval)
            await self.reconcile_deliveries()

    def start_delivery_scan(self) -> None:
        if self.delivery_scan_task is None or self.delivery_scan_task.done():
            self.delivery_scan_task = asyncio.create_task(self.delivery_scan_loop())

    async def stop_delivery_scan(self) -> None:
        if self.delivery_scan_task is not None:
            self.delivery_scan_task.cancel()
            try:
                await self.delivery_scan_task
            except asyncio.CancelledError:
                pass
            self.delivery_scan_task = None
        tasks = list(self.delivery_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reply(
        self,
        interaction: RelayInteraction,
        content: str,
        *,
        ephemeral: bool = True,
        outcome: str = "accepted",
        connection: Connection | None = None,
        installation_id: str | None = None,
        profile_id: str | None = None,
    ) -> RelayReply:
        """Persist a redacted command audit and return an explicit reply."""

        audit = self.store.record_audit(
            installation_id=installation_id or (connection.installation_id if connection else None),
            connection_id=connection.id if connection else None,
            profile_id=profile_id or (connection.profile_id if connection else None),
            application_id=interaction.application_id,
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            user_id=interaction.user_id,
            command=interaction.subcommand,
            outcome=outcome,
            safe_detail=self._AUDIT_DETAILS[outcome],
        )
        audit_installation = audit.installation_id
        if audit_installation:
            await self.send_host(
                audit_installation,
                {
                    "type": "command_audit",
                    "protocol_version": PROTOCOL_VERSION,
                    "id": audit.id,
                    "installation_id": audit.installation_id,
                    "connection_id": audit.connection_id,
                    "profile_id": audit.profile_id,
                    "application_id": audit.application_id,
                    "guild_id": audit.guild_id,
                    "channel_id": audit.channel_id,
                    "user_id": audit.user_id,
                    "command": audit.command,
                    "outcome": audit.outcome,
                    "result": audit.outcome,
                    "safe_detail": audit.safe_detail,
                    "created_at": audit.created_at.isoformat(),
                    "timestamp": audit.created_at.isoformat(),
                },
            )
        return RelayReply(content[:2000], ephemeral)

    def _prune_limits(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.interaction_cooldown_seconds)
        while self.interaction_limits:
            key = next(iter(self.interaction_limits))
            if self.interaction_limits[key] >= cutoff:
                break
            self.interaction_limits.pop(key)
        while len(self.interaction_limits) > self.max_interaction_entries:
            self.interaction_limits.popitem(last=False)

    def _interaction_rate_limited(
        self, connection: Connection, interaction: RelayInteraction
    ) -> bool:
        now = datetime.now(UTC)
        self._prune_limits(now)
        key = (connection.id, interaction.user_id, interaction.subcommand)
        previous = self.interaction_limits.get(key)
        if (
            previous is not None
            and (now - previous).total_seconds() < self.interaction_cooldown_seconds
        ):
            return True
        self.interaction_limits.pop(key, None)
        if len(self.interaction_limits) >= self.max_interaction_entries:
            self.interaction_limits.popitem(last=False)
        self.interaction_limits[key] = now
        return False

    def _pair_rate_limited(self, interaction: RelayInteraction) -> bool:
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=self.pair_attempt_window_seconds)
        while self.pair_attempts:
            key = next(iter(self.pair_attempts))
            attempts = [item for item in self.pair_attempts[key] if item >= cutoff]
            if attempts:
                self.pair_attempts[key] = attempts
                break
            self.pair_attempts.pop(key)
        key = (
            interaction.application_id,
            interaction.guild_id,
            interaction.channel_id,
            interaction.user_id,
        )
        attempts = [item for item in self.pair_attempts.get(key, []) if item >= cutoff]
        self.pair_attempts.pop(key, None)
        if len(attempts) >= self.pair_attempt_limit:
            self.pair_attempts[key] = attempts
            return True
        attempts.append(now)
        if len(self.pair_attempts) >= self.max_pair_attempt_entries:
            self.pair_attempts.popitem(last=False)
        self.pair_attempts[key] = attempts
        return False

    async def interaction(self, interaction: RelayInteraction) -> RelayReply:
        command = interaction.subcommand
        # Setup is deliberately public and contains no installation or channel
        # information.  It is safe even before the application is paired.
        if command == "setup":
            return await self._reply(
                interaction,
                "**Blockstead first-time setup**\n"
                "1. The Blockstead owner creates a pairing code in the Blockstead dashboard.\n"
                "2. Run `/blockstead pair code:<code>` in this channel.\n"
                "3. The owner confirms this exact channel in Blockstead.\n\n"
                "Use one Discord channel for each Minecraft server.",
                ephemeral=False,
            )
        if command == "help":
            return await self._reply(
                interaction,
                "Use `/blockstead setup` before pairing. Paired channels provide status, "
                "players, address, refresh, and unpair commands.",
            )
        if interaction.application_id != self.settings.application_id:
            return await self._reply(interaction, self.generic_denial, outcome="denied")
        if command == "pair":
            if self._pair_rate_limited(interaction):
                return await self._reply(interaction, self.generic_denial, outcome="rate_limited")
            code = str(interaction.options.get("code", "")).strip()
            try:
                pairing = self.store.claim_pairing(
                    code,
                    interaction.application_id,
                    interaction.guild_id,
                    interaction.channel_id,
                    interaction.user_id,
                    interaction.role_ids,
                )
            except (LookupError, ValueError):
                return await self._reply(
                    interaction,
                    "That pairing code is not valid, has expired, or this channel is already "
                    "paired.",
                    outcome="failed",
                )
            await self.send_host(
                pairing.installation_id, {"type": "pairing_claimed", **pairing_payload(pairing)}
            )
            return await self._reply(
                interaction,
                "Pairing request received. Confirm this exact Discord channel in Blockstead.",
                installation_id=pairing.installation_id,
                profile_id=pairing.profile_id,
            )
        connection = self.store.connection_for_discord(
            interaction.application_id, interaction.guild_id, interaction.channel_id
        )
        if connection is None:
            return await self._reply(interaction, self.generic_denial, outcome="denied")
        if self.store.is_stale(connection, self.settings.stale_after_seconds):
            return await self._reply(
                interaction, self.generic_denial, outcome="denied", connection=connection
            )
        if command in {"status", "players", "address"}:
            if not (
                interaction.user_id in connection.authorized_user_ids
                or set(interaction.role_ids).intersection(connection.authorized_role_ids)
            ):
                return await self._reply(
                    interaction, self.generic_denial, outcome="denied", connection=connection
                )
        elif command in {"refresh", "unpair"}:
            if interaction.user_id != connection.owner_user_id:
                return await self._reply(
                    interaction, self.generic_denial, outcome="denied", connection=connection
                )
        else:
            # Unknown/unsupported subcommands must not use the fact that a
            # channel is paired as an oracle.  Apply the same read principal
            # boundary before returning the generic denial for both owners and
            # unauthorized users.
            if not (
                interaction.user_id in connection.authorized_user_ids
                or set(interaction.role_ids).intersection(connection.authorized_role_ids)
            ):
                return await self._reply(
                    interaction, self.generic_denial, outcome="denied", connection=connection
                )
        if command not in {"status", "players", "address", "refresh", "unpair"}:
            return await self._reply(
                interaction, self.generic_denial, outcome="denied", connection=connection
            )
        if command not in {"unpair", "refresh"} and self._interaction_rate_limited(
            connection, interaction
        ):
            return await self._reply(
                interaction, "Please wait a few seconds before trying that command again.",
                outcome="rate_limited", connection=connection
            )
        if command == "address" and not connection.share_address:
            return await self._reply(
                interaction,
                "Address sharing is disabled for this connection.",
                connection=connection,
            )
        if command == "unpair":
            revoked = self.store.revoke_connection_for_discord(
                connection.id,
                interaction.application_id,
                interaction.guild_id,
                interaction.channel_id,
                interaction.user_id,
            )
            await self.send_host(
                connection.installation_id,
                {
                    "type": "connection_revoked",
                    "id": revoked.id,
                    **binding_payload(revoked),
                    "revoked_at": revoked.revoked_at.isoformat()
                    if revoked.revoked_at
                    else None,
                },
            )
            return await self._reply(
                interaction, "This Blockstead connection has been revoked.", connection=connection
            )
        if command == "refresh":
            key = (connection.id, interaction.user_id)
            previous = self.refreshes.get(key)
            now = datetime.now(UTC)
            cutoff = now - timedelta(seconds=self.refresh_cooldown_seconds)
            while self.refreshes:
                oldest_key = next(iter(self.refreshes))
                if self.refreshes[oldest_key] >= cutoff:
                    break
                del self.refreshes[oldest_key]
            if (
                previous is not None
                and (now - previous).total_seconds() < self.refresh_cooldown_seconds
            ):
                return await self._reply(
                    interaction,
                    "Please wait a few seconds before requesting another refresh.",
                    outcome="rate_limited",
                    connection=connection,
                )
            self.refreshes.pop(key, None)
            if len(self.refreshes) >= self.max_refresh_entries:
                self.refreshes.popitem(last=False)
            self.refreshes[key] = now
            await self.send_host(
                connection.installation_id,
                {"type": "refresh", **binding_payload(connection)},
            )
            return await self._reply(
                interaction, "A fresh status check was requested.", connection=connection
            )
        snapshot = self.store.snapshot(connection, self.settings.stale_after_seconds)
        if command == "status":
            if snapshot is None:
                content = f"**{connection.profile_name}** is waiting for a host update."
            else:
                freshness = " (stale)" if snapshot.get("stale") else ""
                content = (
                    f"**{connection.profile_name}** is "
                    f"**{str(snapshot.get('state', 'unknown'))}**{freshness}."
                )
            return await self._reply(interaction, content, connection=connection)
        if command == "players":
            players = snapshot.get("players") if isinstance(snapshot, dict) else None
            if (
                isinstance(players, dict)
                and players.get("online") is not None
                and players.get("max") is not None
            ):
                content = (
                    f"**{connection.profile_name}** players: "
                    f"**{players['online']}/{players['max']}**."
                )
            else:
                content = f"**{connection.profile_name}** player count is unavailable."
            return await self._reply(interaction, content, connection=connection)
        if command == "address":
            public = snapshot.get("public") if isinstance(snapshot, dict) else None
            address = public.get("address") if isinstance(public, dict) else None
            content = (
                f"Join address: `{address}`."
                if address
                else "A public join address is unavailable."
            )
            return await self._reply(interaction, content, connection=connection)
        return await self._reply(
            interaction,
            "That Blockstead command is not available.",
            outcome="failed",
            connection=connection,
        )


def create_app(settings: RelaySettings | None = None) -> FastAPI:
    config = settings or RelaySettings()
    runtime = RelayRuntime(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime.gateway = DiscordGateway(
            config.application_id,
            config.bot_token,
            runtime.interaction,
            on_readiness=runtime.gateway_readiness,
            logger=log,
        )
        runtime.gateway.start()
        runtime.start_delivery_scan()
        yield
        await runtime.stop_delivery_scan()
        if runtime.gateway is not None:
            await runtime.gateway.stop()
        runtime.store.close()

    app = FastAPI(title="Blockstead Discord Relay", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime

    @app.get("/healthz")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "discord_online": runtime.gateway.connected if runtime.gateway else False,
            "discord_ready": runtime.gateway.ready if runtime.gateway else False,
            "discord_heartbeat_healthy": (
                runtime.gateway.heartbeat_healthy if runtime.gateway else False
            ),
            "connected_hosts": len(runtime.hosts),
        }

    @app.post("/v1/pairings/register", status_code=201)
    async def register_pairing(payload: PairingRegister) -> dict[str, object]:
        try:
            pairing = runtime.store.register_pairing(**payload.model_dump())
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        except ValueError as exc:
            raise HTTPException(409, "That profile already has a relay connection.") from exc
        return pairing_payload(pairing)

    @app.post("/v1/installations/register")
    async def register_installation(payload: InstallationRegister) -> dict[str, bool]:
        try:
            runtime.store.register_installation(**payload.model_dump())
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        return {"registered": True}

    @app.post("/v1/installations/rotation/prepare")
    @app.post("/v1/connector/rotation/prepare")
    async def prepare_rotation(payload: RotationPrepare) -> dict[str, object]:
        try:
            status = runtime.store.prepare_rotation(
                payload.installation_id,
                payload.connector_secret,
                payload.replacement_secret,
                ttl_seconds=payload.ttl_seconds,
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        except ValueError as exc:
            raise HTTPException(422, "The connector rotation request was invalid.") from exc
        await runtime.close_host(payload.installation_id)
        return {
            "installation_id": status.installation_id,
            "pending": status.pending,
            "expires_at": status.expires_at.isoformat() if status.expires_at else None,
            "reconnect_required": True,
        }

    @app.post("/v1/installations/rotation/cancel")
    @app.post("/v1/connector/rotation/cancel")
    async def cancel_rotation(payload: RotationControl) -> dict[str, object]:
        try:
            status = runtime.store.cancel_rotation(
                payload.installation_id, payload.connector_secret
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        return {
            "installation_id": status.installation_id,
            "pending": status.pending,
            "expires_at": None,
        }

    @app.post("/v1/installations/rotation/status")
    @app.post("/v1/connector/rotation/status")
    async def rotation_status(payload: RotationControl) -> dict[str, object]:
        try:
            status = runtime.store.rotation_status(
                payload.installation_id, payload.connector_secret
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        return {
            "installation_id": status.installation_id,
            "pending": status.pending,
            "expires_at": status.expires_at.isoformat() if status.expires_at else None,
        }

    @app.post("/v1/pairings/{pairing_id}/confirm")
    async def confirm_pairing(pairing_id: str, payload: PairingConfirm) -> dict[str, object]:
        try:
            connection = runtime.store.confirm_pairing(
                pairing_id, payload.installation_id, payload.connector_secret
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        except (LookupError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        await runtime.send_host(
            connection.installation_id,
            {"type": "connection_activated", **connection_payload(connection)},
        )
        await runtime.publish(connection)
        latest = runtime.store.connection(connection.id) or connection
        return connection_payload(latest)

    @app.patch("/v1/connections/{connection_id}")
    async def change_connection(connection_id: str, payload: ConnectionChange) -> dict[str, object]:
        try:
            connection = runtime.store.update_connection(
                connection_id,
                payload.installation_id,
                payload.connector_secret,
                enabled=payload.enabled,
                share_address=payload.share_address,
                publish_address=payload.publish_address,
                authorized_user_ids=payload.authorized_user_ids,
                authorized_role_ids=payload.authorized_role_ids,
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        except LookupError as exc:
            raise HTTPException(404, "That relay connection was not found.") from exc
        except ValueError as exc:
            raise HTTPException(422, "The relay connection changes were invalid.") from exc
        await runtime.send_host(
            connection.installation_id,
            {"type": "connection_changed", **connection_payload(connection)},
        )
        if connection.enabled:
            await runtime.publish(connection)
        latest = runtime.store.connection(connection.id) or connection
        return connection_payload(latest)

    @app.delete("/v1/connections/{connection_id}")
    async def delete_connection(connection_id: str, payload: PairingConfirm) -> dict[str, object]:
        try:
            connection = runtime.store.revoke_connection(
                connection_id, payload.installation_id, payload.connector_secret
            )
        except (LookupError, PermissionError) as exc:
            raise HTTPException(404, "That relay connection was not found.") from exc
        await runtime.send_host(
            connection.installation_id,
            {
                "type": "connection_revoked",
                "id": connection.id,
                **binding_payload(connection),
                "revoked_at": connection.revoked_at.isoformat()
                if connection.revoked_at
                else None,
            },
        )
        return {"revoked": True}

    @app.websocket("/v1/connect")
    async def connect_host(socket: WebSocket) -> None:
        await socket.accept()
        installation_id: str | None = None
        try:
            hello = await socket.receive_json()
            if not isinstance(hello, dict) or hello.get("type") != "hello":
                await socket.close(code=1008)
                return
            if hello.get("protocol_version") != PROTOCOL_VERSION:
                await socket.close(code=1008)
                return
            installation_id = str(hello.get("installation_id", ""))
            secret = str(hello.get("connector_secret", ""))
            if not runtime.store.authenticate_connector(installation_id, secret):
                await socket.close(code=1008)
                return
            async with runtime.host_lock:
                runtime.hosts[installation_id] = socket
            await socket.send_json(
                {
                    "type": "hello_ok",
                    "protocol_version": PROTOCOL_VERSION,
                    "installation_id": installation_id,
                    "discord_ready": runtime.gateway.ready if runtime.gateway else False,
                    "heartbeat_healthy": (
                        runtime.gateway.heartbeat_healthy if runtime.gateway else False
                    ),
                }
            )
            for pairing in runtime.store.pending_for_installation(installation_id):
                await socket.send_json({"type": "pairing_claimed", **pairing_payload(pairing)})
            for replayed_connection in runtime.store.connections_for_installation(installation_id):
                if replayed_connection.enabled:
                    await socket.send_json(
                        {
                            "type": "connection_activated",
                            "connection_id": replayed_connection.id,
                            **connection_payload(
                                replayed_connection,
                                stale=runtime.store.is_stale(
                                    replayed_connection, runtime.settings.stale_after_seconds
                                ),
                            ),
                        }
                    )
            for revoked_connection in runtime.store.revocations_for_installation(
                installation_id
            ):
                await socket.send_json(
                    {
                        "type": "connection_revoked",
                        **binding_payload(revoked_connection),
                        "revoked_at": revoked_connection.revoked_at.isoformat()
                        if revoked_connection.revoked_at
                        else None,
                    }
                )
            async for message in socket.iter_json():
                if not isinstance(message, dict):
                    continue
                if message.get("protocol_version") != PROTOCOL_VERSION:
                    await socket.close(code=1008)
                    return
                connection_id = str(message.get("connection_id", ""))
                message_type = message.get("type")
                host_connection_types = {
                    "profile_binding_unavailable",
                    "profile_unavailable",
                    "binding_unavailable",
                    "binding_status",
                    "profile_binding",
                    "profile_deleted",
                    "heartbeat",
                    "status",
                }
                if message_type not in host_connection_types:
                    await socket.close(code=1008)
                    return
                binding = runtime.store.connection(connection_id) if connection_id else None
                if message_type in host_connection_types and (
                    binding is None
                    or any(
                        message.get(key) != expected
                        for key, expected in (
                            ("installation_id", installation_id),
                            ("connection_id", binding.id),
                            ("profile_id", binding.profile_id),
                            ("application_id", binding.application_id),
                            ("guild_id", binding.guild_id),
                            ("channel_id", binding.channel_id),
                        )
                    )
                ):
                    await socket.close(code=1008)
                    return
                if message_type in {
                    "profile_binding_unavailable",
                    "profile_unavailable",
                    "binding_unavailable",
                    "binding_status",
                    "profile_binding",
                    "profile_deleted",
                }:
                    assert binding is not None
                    binding_mismatch = (
                        isinstance(message.get("profile_id"), str)
                        and message.get("profile_id") != binding.profile_id
                    )
                    unavailable = (
                        message.get("available") is False or message.get("enabled") is False
                    )
                    if (
                        connection_id
                        and binding.installation_id == installation_id
                        and (
                            unavailable
                            or binding_mismatch
                            or message.get("type")
                            in {
                                "profile_binding_unavailable",
                                "profile_unavailable",
                                "profile_deleted",
                            }
                        )
                    ):
                        revoked = runtime.store.revoke_missing_profile_binding(
                            connection_id, installation_id, secret
                        )
                        if revoked:
                            tombstone = runtime.store.connection(
                                connection_id, include_revoked=True
                            )
                            if tombstone is not None:
                                await runtime.send_host(
                                    installation_id,
                                    {
                                        "type": "connection_revoked",
                                        "id": tombstone.id,
                                        **binding_payload(tombstone),
                                        "reason": "profile_unavailable",
                                        "revoked_at": tombstone.revoked_at.isoformat()
                                        if tombstone.revoked_at
                                        else None,
                                    },
                                )
                    continue
                connection = runtime.store.connection(connection_id)
                if connection is None or connection.installation_id != installation_id:
                    continue
                if message.get("type") == "heartbeat":
                    if runtime.store.heartbeat(connection_id, installation_id, secret):
                        updated = runtime.store.connection(connection_id)
                        if updated is not None and updated.last_heartbeat_at is not None:
                            await runtime.send_host(
                                installation_id,
                                {
                                    "type": "connection_heartbeat",
                                    **binding_payload(updated),
                                    "received_at": updated.last_heartbeat_at.isoformat(),
                                },
                            )
                elif message.get("type") == "status":
                    sequence = message.get("sequence")
                    if not isinstance(sequence, int) or isinstance(sequence, bool):
                        await socket.close(code=1008)
                        return
                    snapshot = message.get("snapshot")
                    try:
                        normalized = (
                            bounded_snapshot(snapshot, share_address=connection.share_address)
                            if isinstance(snapshot, dict)
                            else None
                        )
                    except ValueError:
                        await socket.close(code=1008)
                        return
                    if normalized is None:
                        await socket.close(code=1008)
                        return
                    if runtime.store.save_snapshot(
                        connection_id,
                        installation_id,
                        secret,
                        sequence,
                        normalized,
                    ):
                        updated = runtime.store.connection(connection_id)
                        if updated is not None:
                            await runtime.publish(updated)
        except (WebSocketDisconnect, ValueError, RuntimeError):
            pass
        finally:
            if installation_id is not None:
                async with runtime.host_lock:
                    if runtime.hosts.get(installation_id) is socket:
                        runtime.hosts.pop(installation_id, None)

    return app


try:
    app = create_app()
except Exception:
    # Keep imports and local tooling usable before relay environment variables
    # are supplied. Production uses the configured app from the same module.
    app = FastAPI(title="Blockstead Discord Relay")
