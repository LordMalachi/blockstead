from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .config import RelaySettings
from .discord import DiscordError, DiscordGateway
from .protocol import RelayInteraction
from .store import Connection, Pairing, RelayStore

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
    publish_address: bool | None = None


def bounded_snapshot(snapshot: dict[str, Any]) -> dict[str, object]:
    """Keep relay snapshots to the intentionally small public status contract."""

    result: dict[str, object] = {}
    state = snapshot.get("state")
    if isinstance(state, str):
        result["state"] = state[:32]
    players = snapshot.get("players")
    if isinstance(players, dict):
        result["players"] = {
            key: players[key]
            for key in ("online", "max")
            if isinstance(players.get(key), int) and players[key] >= 0
        }
    public = snapshot.get("public")
    if isinstance(public, dict):
        public_snapshot: dict[str, object] = {}
        address = public.get("address")
        address_state = public.get("state")
        if isinstance(address, str):
            public_snapshot["address"] = address[:255]
        if isinstance(address_state, str):
            public_snapshot["state"] = address_state[:32]
        if public_snapshot:
            result["public"] = public_snapshot
    return result


def pairing_payload(pairing: Pairing) -> dict[str, object]:
    return {
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
        "claimed_at": pairing.claimed_at.isoformat() if pairing.claimed_at else None,
        "confirmed_at": pairing.confirmed_at.isoformat() if pairing.confirmed_at else None,
    }


def connection_payload(connection: Connection, *, stale: bool = False) -> dict[str, object]:
    return {
        "id": connection.id,
        "installation_id": connection.installation_id,
        "profile_id": connection.profile_id,
        "profile_name": connection.profile_name,
        "application_id": connection.application_id,
        "guild_id": connection.guild_id,
        "channel_id": connection.channel_id,
        "owner_user_id": connection.owner_user_id,
        "enabled": connection.enabled,
        "publish_address": connection.publish_address,
        "status_message_id": connection.status_message_id,
        "last_sequence": connection.last_sequence,
        "last_heartbeat_at": connection.last_heartbeat_at.isoformat()
        if connection.last_heartbeat_at
        else None,
        "stale": stale,
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

    def __init__(self, settings: RelaySettings) -> None:
        self.settings = settings
        self.store = RelayStore(settings.database_path)
        self.gateway: DiscordGateway | None = None
        self.hosts: dict[str, WebSocket] = {}
        self.host_lock = asyncio.Lock()
        self.refreshes: OrderedDict[tuple[str, str], datetime] = OrderedDict()

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

    async def publish(self, connection: Connection) -> None:
        snapshot = self.store.snapshot(connection, self.settings.stale_after_seconds)
        content = render_status(connection, snapshot)
        try:
            assert self.gateway is not None
            if connection.status_message_id:
                await self.gateway.rest.edit_message(
                    connection.channel_id, connection.status_message_id, content
                )
            else:
                message_id = await self.gateway.rest.create_message(connection.channel_id, content)
                self.store.set_status_message(connection.id, message_id)
        except (DiscordError, AssertionError):
            log.warning("Could not publish one Blockstead status message")

    async def interaction(self, interaction: RelayInteraction) -> str:
        if interaction.application_id != self.settings.application_id:
            return "This Discord application is not authorized for Blockstead."
        command = interaction.subcommand
        if command == "setup":
            return (
                "**Blockstead first-time setup**\n"
                "1. The Blockstead owner creates a pairing code in the Blockstead dashboard.\n"
                "2. Run `/blockstead pair code:<code>` in this channel.\n"
                "3. The owner confirms this exact channel in Blockstead.\n\n"
                "Use one Discord channel for each Minecraft server."
            )
        if command == "help":
            return (
                "Use `/blockstead setup` before pairing. Paired channels provide status, "
                "players, address, refresh, and unpair commands."
            )
        if command == "pair":
            code = str(interaction.options.get("code", "")).strip()
            try:
                pairing = self.store.claim_pairing(
                    code,
                    interaction.application_id,
                    interaction.guild_id,
                    interaction.channel_id,
                    interaction.user_id,
                )
            except (LookupError, ValueError):
                return (
                    "That pairing code is not valid, has expired, or this channel is already "
                    "paired."
                )
            await self.send_host(
                pairing.installation_id, {"type": "pairing_claimed", **pairing_payload(pairing)}
            )
            return "Pairing request received. Confirm this exact Discord channel in Blockstead."
        connection = self.store.connection_for_discord(
            interaction.application_id, interaction.guild_id, interaction.channel_id
        )
        if connection is None:
            return (
                "This channel is not paired with Blockstead. Run `/blockstead setup` for "
                "instructions."
            )
        if command == "unpair" and interaction.user_id != connection.owner_user_id:
            return "Only the person who paired this connection can unpair it."
        if command == "unpair":
            self.store.revoke_connection(connection.id, connection.installation_id)
            await self.send_host(
                connection.installation_id,
                {"type": "connection_revoked", "id": connection.id, "connection_id": connection.id},
            )
            return "This Blockstead connection has been revoked."
        if command == "refresh":
            key = (connection.id, interaction.user_id)
            previous = self.refreshes.get(key)
            now = datetime.now(UTC)
            cutoff = now - timedelta(seconds=self.refresh_cooldown_seconds)
            # self.refreshes is kept in chronological (oldest-first) order by
            # always re-inserting a written key at the end, so both pruning
            # and capacity eviction only ever need to look at the front.
            while self.refreshes:
                oldest_key = next(iter(self.refreshes))
                if self.refreshes[oldest_key] >= cutoff:
                    break
                del self.refreshes[oldest_key]
            if (
                previous is not None
                and (now - previous).total_seconds() < self.refresh_cooldown_seconds
            ):
                return "Please wait a few seconds before requesting another refresh."
            self.refreshes.pop(key, None)
            if len(self.refreshes) >= self.max_refresh_entries:
                self.refreshes.popitem(last=False)
            self.refreshes[key] = now
            await self.send_host(
                connection.installation_id, {"type": "refresh", "connection_id": connection.id}
            )
            return "A fresh status check was requested."
        snapshot = self.store.snapshot(connection, self.settings.stale_after_seconds)
        if command == "status":
            if snapshot is None:
                return f"**{connection.profile_name}** is waiting for a host update."
            freshness = " (stale)" if snapshot.get("stale") else ""
            return (
                f"**{connection.profile_name}** is "
                f"**{str(snapshot.get('state', 'unknown'))}**{freshness}."
            )
        if command == "players":
            players = snapshot.get("players") if isinstance(snapshot, dict) else None
            if (
                isinstance(players, dict)
                and players.get("online") is not None
                and players.get("max") is not None
            ):
                return (
                    f"**{connection.profile_name}** players: "
                    f"**{players['online']}/{players['max']}**."
                )
            return f"**{connection.profile_name}** player count is unavailable."
        if command == "address":
            if not connection.publish_address:
                return "Address sharing is disabled for this connection."
            public = snapshot.get("public") if isinstance(snapshot, dict) else None
            address = public.get("address") if isinstance(public, dict) else None
            return (
                f"Join address: `{address}`."
                if address
                else "A public join address is unavailable."
            )
        return "That Blockstead command is not available."


def create_app(settings: RelaySettings | None = None) -> FastAPI:
    config = settings or RelaySettings()
    runtime = RelayRuntime(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        runtime.gateway = DiscordGateway(
            config.application_id, config.bot_token, runtime.interaction, logger=log
        )
        runtime.gateway.start()
        yield
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
            "connected_hosts": len(runtime.hosts),
        }

    @app.post("/v1/pairings/register", status_code=201)
    async def register_pairing(payload: PairingRegister) -> dict[str, object]:
        try:
            pairing = runtime.store.register_pairing(**payload.model_dump())
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        return pairing_payload(pairing)

    @app.post("/v1/installations/register")
    async def register_installation(payload: InstallationRegister) -> dict[str, bool]:
        try:
            runtime.store.register_installation(**payload.model_dump())
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        return {"registered": True}

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
        return connection_payload(connection)

    @app.patch("/v1/connections/{connection_id}")
    async def change_connection(connection_id: str, payload: ConnectionChange) -> dict[str, object]:
        try:
            connection = runtime.store.update_connection(
                connection_id,
                payload.installation_id,
                payload.connector_secret,
                enabled=payload.enabled,
                publish_address=payload.publish_address,
            )
        except PermissionError as exc:
            raise HTTPException(403, "The relay connector credentials were rejected.") from exc
        except LookupError as exc:
            raise HTTPException(404, "That relay connection was not found.") from exc
        await runtime.send_host(
            connection.installation_id,
            {"type": "connection_changed", **connection_payload(connection)},
        )
        await runtime.publish(connection)
        return connection_payload(connection)

    @app.delete("/v1/connections/{connection_id}")
    async def delete_connection(connection_id: str, payload: PairingConfirm) -> dict[str, object]:
        connection = runtime.store.connection(connection_id)
        if (
            connection is None
            or not runtime.store.authenticate(payload.installation_id, payload.connector_secret)
            or connection.installation_id != payload.installation_id
        ):
            raise HTTPException(404, "That relay connection was not found.")
        runtime.store.revoke_connection(connection_id, payload.installation_id)
        await runtime.send_host(
            connection.installation_id,
            {"type": "connection_revoked", "id": connection_id, "connection_id": connection_id},
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
            installation_id = str(hello.get("installation_id", ""))
            secret = str(hello.get("connector_secret", ""))
            if not runtime.store.authenticate(installation_id, secret):
                await socket.close(code=1008)
                return
            async with runtime.host_lock:
                runtime.hosts[installation_id] = socket
            await socket.send_json({"type": "hello_ok"})
            for pairing in runtime.store.pending_for_installation(installation_id):
                await socket.send_json({"type": "pairing_claimed", **pairing_payload(pairing)})
            async for message in socket.iter_json():
                if not isinstance(message, dict):
                    continue
                connection_id = str(message.get("connection_id", ""))
                connection = runtime.store.connection(connection_id)
                if connection is None or connection.installation_id != installation_id:
                    continue
                if message.get("type") == "heartbeat":
                    runtime.store.heartbeat(connection_id, installation_id)
                elif message.get("type") == "status":
                    sequence = int(message.get("sequence", 0))
                    snapshot = message.get("snapshot")
                    if isinstance(snapshot, dict) and runtime.store.save_snapshot(
                        connection_id, installation_id, sequence, bounded_snapshot(snapshot)
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
