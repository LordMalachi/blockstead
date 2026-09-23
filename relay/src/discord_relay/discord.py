from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from websockets.asyncio.client import connect

from .protocol import RelayInteraction, RelayReply, command_definition, parse_interaction

DISCORD_API = "https://discord.com/api/v10"
GUILDS_INTENT = 1


class DiscordError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status_code is None or self.status_code == 429 or self.status_code >= 500


class DiscordRest:
    def __init__(self, application_id: str, token: str) -> None:
        self.application_id = application_id
        self._client = httpx.AsyncClient(
            base_url=DISCORD_API,
            headers={"Authorization": f"Bot {token}", "User-Agent": "Blockstead Discord relay"},
            timeout=httpx.Timeout(10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise DiscordError("Discord rejected the relay request") from exc
        if response.is_error:
            retry_after: float | None = None
            if response.status_code == 429:
                raw_retry_after: object = response.headers.get("Retry-After")
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and body.get("retry_after") is not None:
                    raw_retry_after = body["retry_after"]
                try:
                    retry_after = (
                        max(1.0, min(300.0, float(raw_retry_after)))
                        if isinstance(raw_retry_after, str | int | float)
                        else 1.0
                    )
                except ValueError:
                    retry_after = 1.0
            raise DiscordError(
                "Discord rejected the relay request",
                status_code=response.status_code,
                retry_after=retry_after,
            )
        return response

    async def register_guild(self, guild_id: str) -> None:
        await self.request(
            "PUT",
            f"/applications/{self.application_id}/guilds/{guild_id}/commands",
            json=[command_definition()],
        )

    async def respond(
        self, interaction: RelayInteraction, content: str, *, ephemeral: bool = True
    ) -> None:
        await self.request(
            "POST",
            f"/interactions/{interaction.interaction_id}/{interaction.interaction_token}/callback",
            json={
                "type": 4,
                "data": {
                    "content": content[:2000],
                    "flags": 64 if ephemeral else 0,
                    "allowed_mentions": {"parse": []},
                },
            },
        )

    async def create_message(self, channel_id: str, content: str) -> str:
        response = await self.request(
            "POST",
            f"/channels/{channel_id}/messages",
            json={"content": content[:2000], "allowed_mentions": {"parse": []}},
        )
        message_id = response.json().get("id")
        if not isinstance(message_id, str):
            raise DiscordError("Discord did not return a message ID")
        return message_id

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
        await self.request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            json={"content": content[:2000], "allowed_mentions": {"parse": []}},
        )


class DiscordGateway:
    url = "wss://gateway.discord.gg/?v=10&encoding=json"

    def __init__(
        self,
        application_id: str,
        token: str,
        on_interaction: Callable[[RelayInteraction], Awaitable[RelayReply]],
        *,
        on_readiness: Callable[[bool, bool], Awaitable[None]] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.application_id = application_id
        self.rest = DiscordRest(application_id, token)
        self._on_interaction = on_interaction
        self._on_readiness = on_readiness
        self._log = logger or logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._socket: Any = None
        self._connected = False
        self._ready_seen = False
        self._heartbeat_healthy = False
        self._awaiting_heartbeat_ack = False
        self._sequence: int | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def ready(self) -> bool:
        return self._connected

    @property
    def heartbeat_healthy(self) -> bool:
        return self._heartbeat_healthy

    async def _set_readiness(self) -> None:
        ready = self._ready_seen and self._heartbeat_healthy
        changed = ready != self._connected
        self._connected = ready
        if changed and self._on_readiness is not None:
            await self._on_readiness(ready, self._heartbeat_healthy)

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
        self._ready_seen = False
        self._heartbeat_healthy = False
        self._awaiting_heartbeat_ack = False
        await self._set_readiness()
        await self.rest.close()

    async def run(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            try:
                async with connect(self.url, max_size=2_000_000, ping_interval=None) as socket:
                    self._socket = socket
                    self._sequence = None
                    self._ready_seen = False
                    self._heartbeat_healthy = False
                    self._awaiting_heartbeat_ack = False
                    await self._set_readiness()
                    await self._session(socket)
                delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._ready_seen = False
                self._heartbeat_healthy = False
                self._awaiting_heartbeat_ack = False
                await self._set_readiness()
                self._log.warning("Discord relay Gateway connection ended; retrying")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    delay = min(60.0, delay * 2)

    async def _session(self, socket: Any) -> None:
        hello = json.loads(await socket.recv())
        data = hello.get("d") if isinstance(hello, dict) else None
        interval = data.get("heartbeat_interval") if isinstance(data, dict) else None
        if not isinstance(interval, int | float):
            raise DiscordError("Discord Gateway hello was invalid")
        heartbeat = asyncio.create_task(self._heartbeat(socket, float(interval) / 1000))
        await socket.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": self.rest._client.headers["Authorization"].removeprefix("Bot "),
                        "intents": GUILDS_INTENT,
                        "properties": {
                            "os": "linux",
                            "browser": "blockstead-relay",
                            "device": "blockstead-relay",
                        },
                    },
                }
            )
        )
        try:
            async for raw in socket:
                event = json.loads(raw)
                if not isinstance(event, dict):
                    continue
                if isinstance(event.get("s"), int):
                    self._sequence = event["s"]
                if event.get("op") == 0:
                    await self._dispatch(event)
                elif event.get("op") == 1:
                    await socket.send(json.dumps({"op": 1, "d": self._sequence}))
                    self._awaiting_heartbeat_ack = True
                elif event.get("op") == 11:
                    self._awaiting_heartbeat_ack = False
                    self._heartbeat_healthy = True
                    await self._set_readiness()
                elif event.get("op") in {7, 9}:
                    break
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            self._ready_seen = False
            self._heartbeat_healthy = False
            self._awaiting_heartbeat_ack = False
            await self._set_readiness()

    async def _heartbeat(self, socket: Any, interval: float) -> None:
        while True:
            if self._awaiting_heartbeat_ack:
                self._heartbeat_healthy = False
                await self._set_readiness()
                await socket.close(code=1011, reason="heartbeat acknowledgement timeout")
                return
            await socket.send(json.dumps({"op": 1, "d": self._sequence}))
            self._awaiting_heartbeat_ack = True
            await asyncio.sleep(interval)

    async def _dispatch(self, event: Mapping[str, object]) -> None:
        name = event.get("t")
        data = event.get("d")
        guild_ids: list[str] = []
        if name == "READY" and isinstance(data, dict):
            self._ready_seen = True
            await self._set_readiness()
            guild_ids = [
                item["id"]
                for item in data.get("guilds", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
        elif name == "GUILD_CREATE" and isinstance(data, dict) and isinstance(data.get("id"), str):
            guild_ids = [data["id"]]
        for guild_id in guild_ids:
            try:
                await self.rest.register_guild(guild_id)
            except DiscordError:
                self._log.warning("Could not register Blockstead commands in one guild")
        if name == "INTERACTION_CREATE" and isinstance(data, dict):
            try:
                interaction = parse_interaction(data)
                reply = await self._on_interaction(interaction)
                await self.rest.respond(interaction, reply.content, ephemeral=reply.ephemeral)
            except (DiscordError, ValueError):
                self._log.warning("Could not complete one Discord interaction safely")
