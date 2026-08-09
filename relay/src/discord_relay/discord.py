from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from websockets.asyncio.client import connect

from .protocol import RelayInteraction, command_definition, parse_interaction

DISCORD_API = "https://discord.com/api/v10"
GUILDS_INTENT = 1


class DiscordError(RuntimeError):
    pass


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

    async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise DiscordError("Discord rejected the relay request") from exc

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
            json={"type": 4, "data": {"content": content[:2000], "flags": 64 if ephemeral else 0}},
        )

    async def create_message(self, channel_id: str, content: str) -> str:
        response = await self.request(
            "POST", f"/channels/{channel_id}/messages", json={"content": content[:2000]}
        )
        message_id = response.json().get("id")
        if not isinstance(message_id, str):
            raise DiscordError("Discord did not return a message ID")
        return message_id

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
        await self.request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            json={"content": content[:2000]},
        )


class DiscordGateway:
    url = "wss://gateway.discord.gg/?v=10&encoding=json"

    def __init__(
        self,
        application_id: str,
        token: str,
        on_interaction: Callable[[RelayInteraction], Awaitable[str]],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.application_id = application_id
        self.rest = DiscordRest(application_id, token)
        self._on_interaction = on_interaction
        self._log = logger or logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._socket: Any = None
        self._connected = False
        self._sequence: int | None = None

    @property
    def connected(self) -> bool:
        return self._connected

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
        self._connected = False
        await self.rest.close()

    async def run(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            try:
                async with connect(self.url, max_size=2_000_000, ping_interval=None) as socket:
                    self._socket = socket
                    self._sequence = None
                    await self._session(socket)
                delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._connected = False
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
        self._connected = True
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
                elif event.get("op") in {7, 9}:
                    break
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            self._connected = False

    async def _heartbeat(self, socket: Any, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await socket.send(json.dumps({"op": 1, "d": self._sequence}))

    async def _dispatch(self, event: Mapping[str, object]) -> None:
        name = event.get("t")
        data = event.get("d")
        guild_ids: list[str] = []
        if name == "READY" and isinstance(data, dict):
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
                await self.rest.respond(interaction, reply, ephemeral=False)
            except (DiscordError, ValueError):
                self._log.warning("Could not complete one Discord interaction safely")
