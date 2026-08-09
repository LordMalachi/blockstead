"""Configuration helpers for the host-side Discord status-bot bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from websockets.asyncio.client import connect

from .config import Settings

DISCORD_API_VERSION = 10
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
# View Channel (1024) + Send Messages (2048) + Embed Links (16384).
# The bot does not need Administrator, Manage Guild, Manage Roles, or member
# list access for the initial read-only status project.
MINIMUM_BOT_PERMISSIONS = 19_456
APPLICATION_ID_PATTERN = re.compile(r"[0-9]{17,20}\Z")
PUBLIC_KEY_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class DiscordConfigurationError(ValueError):
    """A Discord application setting is malformed or incomplete."""


def validate_application_id(value: str) -> str:
    candidate = value.strip()
    if not APPLICATION_ID_PATTERN.fullmatch(candidate):
        raise DiscordConfigurationError("The Discord application ID must be a numeric Discord ID.")
    return candidate


def validate_snowflake(value: str, label: str) -> str:
    candidate = value.strip()
    if not APPLICATION_ID_PATTERN.fullmatch(candidate):
        raise DiscordConfigurationError(f"The Discord {label} must be a numeric Discord ID.")
    return candidate


def validate_public_key(value: str) -> str:
    candidate = value.strip().lower()
    if not PUBLIC_KEY_PATTERN.fullmatch(candidate):
        raise DiscordConfigurationError("The Discord public key must be 64 hexadecimal characters.")
    return candidate


def discord_install_url(application_id: str) -> str:
    """Build the least-privilege guild install URL for this application."""

    app_id = validate_application_id(application_id)
    query = urlencode(
        {
            "client_id": app_id,
            "scope": "bot applications.commands",
            "permissions": str(MINIMUM_BOT_PERMISSIONS),
        }
    )
    return f"{DISCORD_AUTHORIZE_URL}?{query}"


@dataclass(frozen=True)
class DiscordReply:
    """A safe initial response to one slash-command interaction."""

    content: str
    ephemeral: bool = True


@dataclass(frozen=True)
class DiscordInteraction:
    """Only the identity and command data needed by the host-side bridge."""

    interaction_id: str
    interaction_token: str
    application_id: str
    guild_id: str
    channel_id: str
    user_id: str
    role_ids: tuple[str, ...]
    subcommand: str
    options: Mapping[str, object]


def _option_values(options: object) -> dict[str, object]:
    if not isinstance(options, list):
        return {}
    values: dict[str, object] = {}
    for item in options:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        if item.get("type") == 1:
            values.update(_option_values(item.get("options")))
        elif "value" in item:
            values[name] = item["value"]
    return values


def parse_interaction(payload: Mapping[str, object]) -> DiscordInteraction:
    """Parse a Gateway interaction without retaining arbitrary Discord payloads."""

    data = payload.get("data")
    member = payload.get("member")
    user = member.get("user") if isinstance(member, dict) else payload.get("user")
    if not isinstance(data, dict) or not isinstance(user, dict):
        raise DiscordConfigurationError("The Discord interaction was missing command identity.")
    command_options = data.get("options")
    subcommand = ""
    if isinstance(command_options, list) and command_options:
        first = command_options[0]
        if isinstance(first, dict) and first.get("type") == 1:
            subcommand = str(first.get("name", ""))
        else:
            subcommand = str(data.get("name", ""))
    else:
        subcommand = str(data.get("name", ""))
    guild_id = payload.get("guild_id")
    channel_id = payload.get("channel_id")
    interaction_id = payload.get("id")
    token = payload.get("token")
    application_id = payload.get("application_id")
    user_id = user.get("id")
    if not all(
        isinstance(value, str) and value
        for value in (
            guild_id,
            channel_id,
            interaction_id,
            token,
            application_id,
            user_id,
        )
    ):
        raise DiscordConfigurationError("The Discord interaction was missing a required ID.")
    roles = member.get("roles", []) if isinstance(member, dict) else []
    role_ids = (
        tuple(item for item in roles if isinstance(item, str)) if isinstance(roles, list) else ()
    )
    return DiscordInteraction(
        interaction_id=interaction_id,
        interaction_token=token,
        application_id=application_id,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        role_ids=role_ids,
        subcommand=subcommand,
        options=_option_values(command_options),
    )


def blockstead_command_definition() -> dict[str, object]:
    """Return the read-only guild command registered by the host bridge."""

    subcommands = [
        ("status", "Show whether the paired Minecraft server is online."),
        ("players", "Show the current online-player count."),
        ("address", "Show the current join address when the owner allows it."),
        ("refresh", "Refresh the host public-IP observation."),
        ("unpair", "Revoke this Discord connection."),
        ("help", "Show the commands available for this connection."),
        ("setup", "Walk through first-time Blockstead channel setup."),
    ]
    options: list[dict[str, object]] = [
        {"type": 1, "name": name, "description": description} for name, description in subcommands
    ]
    options.insert(
        4,
        {
            "type": 1,
            "name": "pair",
            "description": "Claim a Blockstead pairing code in this channel.",
            "options": [
                {
                    "type": 3,
                    "name": "code",
                    "description": "The one-time code from the Blockstead dashboard.",
                    "required": True,
                    "min_length": 8,
                    "max_length": 32,
                }
            ],
        },
    )
    return {
        "name": "blockstead",
        "description": "Secure Minecraft server status from Blockstead.",
        "type": 1,
        "options": options,
    }


class DiscordApiError(RuntimeError):
    """A Discord REST operation failed without exposing the bearer token."""


class DiscordRestClient:
    """Small REST client for interaction replies and status messages."""

    def __init__(self, application_id: str, token: str) -> None:
        self.application_id = validate_application_id(application_id)
        self._token = token.strip()
        self._client = httpx.AsyncClient(
            base_url=f"https://discord.com/api/{DISCORD_API_VERSION}",
            headers={"Authorization": f"Bot {token}", "User-Agent": "Blockstead Discord bridge"},
            timeout=httpx.Timeout(10.0),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise DiscordApiError("Discord did not accept the host bridge request.") from exc

    async def register_guild_commands(self, guild_id: str) -> None:
        guild = validate_snowflake(guild_id, "guild ID")
        await self._request(
            "PUT",
            f"/applications/{self.application_id}/guilds/{guild}/commands",
            json=[blockstead_command_definition()],
        )

    async def respond_to_interaction(
        self, interaction: DiscordInteraction, reply: DiscordReply
    ) -> None:
        flags = 64 if reply.ephemeral else 0
        await self._request(
            "POST",
            f"/interactions/{interaction.interaction_id}/{interaction.interaction_token}/callback",
            json={"type": 4, "data": {"content": reply.content[:2000], "flags": flags}},
        )

    async def create_message(self, channel_id: str, content: str) -> str:
        channel = validate_snowflake(channel_id, "channel ID")
        response = await self._request(
            "POST", f"/channels/{channel}/messages", json={"content": content[:2000]}
        )
        body = response.json()
        message_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(message_id, str):
            raise DiscordApiError("Discord did not return a status message ID.")
        return message_id

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
        channel = validate_snowflake(channel_id, "channel ID")
        message = validate_snowflake(message_id, "message ID")
        await self._request(
            "PATCH", f"/channels/{channel}/messages/{message}", json={"content": content[:2000]}
        )


class DiscordGateway:
    """Reconnectable outbound Gateway loop with no privileged intents."""

    gateway_url = "wss://gateway.discord.gg/?v=10&encoding=json"

    def __init__(
        self,
        application_id: str,
        token: str,
        on_interaction: Callable[[DiscordInteraction], Awaitable[DiscordReply]],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.application_id = validate_application_id(application_id)
        if not token.strip():
            raise DiscordConfigurationError("A Discord bot token is required.")
        self.rest = DiscordRestClient(self.application_id, token)
        self._on_interaction = on_interaction
        self._log = logger or logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._socket: object | None = None
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
        socket = self._socket
        if socket is not None and hasattr(socket, "close"):
            await socket.close()  # type: ignore[union-attr]
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._connected = False
        await self.rest.close()

    async def run(self) -> None:
        delay = 2.0
        while not self._stop.is_set():
            try:
                async with connect(
                    self.gateway_url, max_size=2_000_000, ping_interval=None
                ) as socket:
                    self._socket = socket
                    self._sequence = None
                    await self._session(socket)
                    self._connected = False
                delay = 2.0
            except asyncio.CancelledError:
                raise
            except Exception:
                self._connected = False
                self._log.warning("The Discord Gateway connection ended; retrying shortly.")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    delay = min(60.0, delay * 2)
        self._connected = False

    async def _session(self, socket: object) -> None:
        hello = json.loads(await socket.recv())  # type: ignore[union-attr]
        if not isinstance(hello, dict) or hello.get("op") != 10:
            raise DiscordApiError("Discord Gateway did not send a valid hello.")
        hello_data = hello.get("d")
        interval_ms = hello_data.get("heartbeat_interval") if isinstance(hello_data, dict) else None
        if not isinstance(interval_ms, int | float):
            raise DiscordApiError("Discord Gateway did not provide a heartbeat interval.")
        heartbeat = asyncio.create_task(self._heartbeat(socket, float(interval_ms) / 1000))
        await self._identify(socket)
        async for raw in socket:  # type: ignore[union-attr]
            event = json.loads(raw)
            if not isinstance(event, dict):
                continue
            if isinstance(event.get("s"), int):
                self._sequence = event["s"]
            op = event.get("op")
            if op == 0:
                await self._dispatch(event)
            elif op == 1:
                await socket.send(json.dumps({"op": 1, "d": self._sequence}))  # type: ignore[union-attr]
            elif op in {7, 9}:
                break
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass

    async def _identify(self, socket: object) -> None:
        await socket.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": self.rest._token,
                        "intents": 0,
                        "properties": {
                            "os": "linux",
                            "browser": "blockstead",
                            "device": "blockstead",
                        },
                    },
                }
            )
        )  # type: ignore[union-attr]
        self._connected = True

    async def _heartbeat(self, socket: object, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await socket.send(json.dumps({"op": 1, "d": self._sequence}))  # type: ignore[union-attr]

    async def _dispatch(self, event: Mapping[str, object]) -> None:
        name = event.get("t")
        data = event.get("d")
        guild_ids: list[str] = []
        if name == "READY" and isinstance(data, dict):
            guilds = data.get("guilds")
            if isinstance(guilds, list):
                guild_ids = [
                    item["id"]
                    for item in guilds
                    if isinstance(item, dict)
                    and item.get("unavailable") is not True
                    and isinstance(item.get("id"), str)
                ]
        elif name == "GUILD_CREATE" and isinstance(data, dict):
            guild_id = data.get("id")
            if isinstance(guild_id, str):
                guild_ids = [guild_id]
        for guild_id in guild_ids:
            try:
                await self.rest.register_guild_commands(guild_id)
            except DiscordApiError:
                self._log.warning("Could not register Blockstead commands for one Discord guild.")
        if name == "INTERACTION_CREATE" and isinstance(data, dict):
            try:
                interaction = parse_interaction(data)
                reply = await self._on_interaction(interaction)
                await self.rest.respond_to_interaction(interaction, reply)
            except (DiscordConfigurationError, DiscordApiError):
                self._log.warning("Could not complete one Discord interaction safely.")


def discord_configuration(settings: Settings) -> dict[str, object]:
    """Return safe legacy Discord metadata; the host never starts this Gateway."""

    application_id = (
        settings.discord_application_id.strip() if settings.discord_application_id else None
    )
    public_key = settings.discord_public_key.strip() if settings.discord_public_key else None
    application_error: str | None = None
    public_key_error: str | None = None
    if application_id:
        try:
            application_id = validate_application_id(application_id)
        except DiscordConfigurationError as exc:
            application_error = str(exc)
    if public_key:
        try:
            public_key = validate_public_key(public_key)
        except DiscordConfigurationError as exc:
            public_key_error = str(exc)
    valid_application = application_id is not None and application_error is None
    relay_configured = bool(settings.discord_relay_url and settings.discord_relay_url.strip())
    legacy_token_configured = bool(settings.discord_bot_token)
    return {
        "application_id": application_id,
        "public_key_configured": public_key is not None and public_key_error is None,
        "bot_token_configured": legacy_token_configured,
        "bot_ready": valid_application and (relay_configured or legacy_token_configured),
        "install_url": discord_install_url(application_id) if valid_application else None,
        "application_error": application_error,
        "public_key_error": public_key_error,
        "mode": (
            "central_relay"
            if valid_application and relay_configured
            else "legacy_host_gateway_disabled"
            if valid_application and legacy_token_configured
            else "not_configured"
        ),
    }
