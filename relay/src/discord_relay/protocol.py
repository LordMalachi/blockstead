from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RelayInteraction:
    interaction_id: str
    interaction_token: str
    application_id: str
    guild_id: str
    channel_id: str
    user_id: str
    subcommand: str
    options: Mapping[str, object]


def _options(value: object) -> dict[str, object]:
    if not isinstance(value, list):
        return {}
    result: dict[str, object] = {}
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        if item.get("type") == 1:
            result.update(_options(item.get("options")))
        elif "value" in item:
            result[item["name"]] = item["value"]
    return result


def parse_interaction(payload: Mapping[str, object]) -> RelayInteraction:
    data = payload.get("data")
    member = payload.get("member")
    user = member.get("user") if isinstance(member, dict) else payload.get("user")
    values = {
        "id": payload.get("id"),
        "token": payload.get("token"),
        "application_id": payload.get("application_id"),
        "guild_id": payload.get("guild_id"),
        "channel_id": payload.get("channel_id"),
        "user_id": user.get("id") if isinstance(user, dict) else None,
    }
    if not isinstance(data, dict) or not all(
        isinstance(value, str) and value for value in values.values()
    ):
        raise ValueError("Discord interaction was missing required identity")
    raw_options = data.get("options")
    subcommand = str(data.get("name", ""))
    if isinstance(raw_options, list) and raw_options and isinstance(raw_options[0], dict):
        if raw_options[0].get("type") == 1:
            subcommand = str(raw_options[0].get("name", ""))
    return RelayInteraction(
        interaction_id=values["id"],
        interaction_token=values["token"],
        application_id=values["application_id"],
        guild_id=values["guild_id"],
        channel_id=values["channel_id"],
        user_id=values["user_id"],
        subcommand=subcommand,
        options=_options(raw_options),
    )


def command_definition() -> dict[str, Any]:
    subcommands = [
        ("status", "Show whether the paired Minecraft server is online."),
        ("players", "Show the current online-player count."),
        ("address", "Show the current join address when allowed."),
        ("refresh", "Ask the Blockstead host for a fresh status."),
        ("unpair", "Revoke this Discord connection."),
        ("help", "Show the commands available for this connection."),
        ("setup", "Walk through first-time Blockstead channel setup."),
    ]
    options: list[dict[str, Any]] = [
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
