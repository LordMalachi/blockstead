"""Versioned, curated Minecraft commands used by the guided console.

The catalog intentionally describes a useful subset rather than pretending to
discover commands registered at runtime.  Its wire format leaves room for a
future companion plugin/mod to merge live Brigadier nodes into the same view.
"""

import re
from typing import Literal, cast

from pydantic import BaseModel, Field

Safety = Literal["normal", "caution", "danger"]
ArgumentKind = Literal["text", "player", "integer", "choice", "resource", "boolean"]


class GuidedCommandRequest(BaseModel):
    profile_id: str
    command_id: str = Field(min_length=1, max_length=80)
    values: dict[str, str | int | bool] = Field(default_factory=dict)
    confirmed: bool = False


COMMANDS: tuple[dict[str, object], ...] = (
    {
        "id": "list",
        "label": "List players",
        "root": "list",
        "category": "Players",
        "description": "Show who is currently online.",
        "safety": "normal",
        "arguments": [],
    },
    {
        "id": "say",
        "label": "Broadcast a message",
        "root": "say",
        "category": "Players",
        "description": "Send a server announcement to every online player.",
        "safety": "normal",
        "arguments": [
            {
                "key": "message",
                "label": "Message",
                "kind": "text",
                "required": True,
                "placeholder": "Server restart in five minutes",
                "max_length": 256,
            },
        ],
    },
    {
        "id": "give",
        "label": "Give an item",
        "root": "give",
        "category": "Items",
        "description": "Give an item to a player or player selector.",
        "safety": "normal",
        "arguments": [
            {
                "key": "target",
                "label": "Who",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName or @a",
                "source": "players",
            },
            {
                "key": "item",
                "label": "Item",
                "kind": "resource",
                "required": True,
                "placeholder": "minecraft:diamond",
                "options": [
                    {"value": "minecraft:apple", "label": "Apple", "icon": "🍎"},
                    {"value": "minecraft:arrow", "label": "Arrow", "icon": "➶"},
                    {"value": "minecraft:baked_potato", "label": "Baked potato", "icon": "🥔"},
                    {"value": "minecraft:bread", "label": "Bread", "icon": "🍞"},
                    {"value": "minecraft:bucket", "label": "Bucket", "icon": "▱"},
                    {"value": "minecraft:coal", "label": "Coal", "icon": "●"},
                    {"value": "minecraft:command_block", "label": "Command block", "icon": "▣"},
                    {"value": "minecraft:diamond", "label": "Diamond", "icon": "◆"},
                    {"value": "minecraft:diamond_axe", "label": "Diamond axe", "icon": "⛏"},
                    {"value": "minecraft:diamond_block", "label": "Block of diamond", "icon": "◇"},
                    {"value": "minecraft:diamond_pickaxe", "label": "Diamond pickaxe", "icon": "⛏"},
                    {"value": "minecraft:diamond_sword", "label": "Diamond sword", "icon": "⚔"},
                    {"value": "minecraft:elytra", "label": "Elytra", "icon": "⌁"},
                    {
                        "value": "minecraft:enchanted_golden_apple",
                        "label": "Enchanted golden apple",
                        "icon": "✦",
                    },
                    {"value": "minecraft:ender_pearl", "label": "Ender pearl", "icon": "●"},
                    {
                        "value": "minecraft:experience_bottle",
                        "label": "Bottle o' enchanting",
                        "icon": "⚗",
                    },
                    {"value": "minecraft:firework_rocket", "label": "Firework rocket", "icon": "↑"},
                    {"value": "minecraft:golden_apple", "label": "Golden apple", "icon": "●"},
                    {"value": "minecraft:iron_ingot", "label": "Iron ingot", "icon": "▰"},
                    {"value": "minecraft:lead", "label": "Lead", "icon": "⌁"},
                    {"value": "minecraft:map", "label": "Empty map", "icon": "▤"},
                    {"value": "minecraft:name_tag", "label": "Name tag", "icon": "▱"},
                    {"value": "minecraft:netherite_ingot", "label": "Netherite ingot", "icon": "▰"},
                    {
                        "value": "minecraft:netherite_pickaxe",
                        "label": "Netherite pickaxe",
                        "icon": "⛏",
                    },
                    {"value": "minecraft:netherite_sword", "label": "Netherite sword", "icon": "⚔"},
                    {"value": "minecraft:oak_log", "label": "Oak log", "icon": "▥"},
                    {"value": "minecraft:paper", "label": "Paper", "icon": "▱"},
                    {"value": "minecraft:redstone", "label": "Redstone dust", "icon": "✣"},
                    {"value": "minecraft:saddle", "label": "Saddle", "icon": "◡"},
                    {"value": "minecraft:shield", "label": "Shield", "icon": "⬟"},
                    {"value": "minecraft:shulker_box", "label": "Shulker box", "icon": "□"},
                    {"value": "minecraft:torch", "label": "Torch", "icon": "♨"},
                    {
                        "value": "minecraft:totem_of_undying",
                        "label": "Totem of undying",
                        "icon": "♜",
                    },
                    {"value": "minecraft:water_bucket", "label": "Water bucket", "icon": "▱"},
                ],
            },
            {
                "key": "amount",
                "label": "How many",
                "kind": "integer",
                "required": False,
                "placeholder": "1",
                "minimum": 1,
                "maximum": 6400,
                "suggestions": [1, 16, 32, 64],
            },
        ],
    },
    {
        "id": "gamemode",
        "label": "Change game mode",
        "root": "gamemode",
        "category": "Players",
        "description": "Change a player's game mode.",
        "safety": "caution",
        "arguments": [
            {
                "key": "mode",
                "label": "Game mode",
                "kind": "choice",
                "required": True,
                "options": ["survival", "creative", "adventure", "spectator"],
            },
            {
                "key": "target",
                "label": "Who",
                "kind": "player",
                "required": False,
                "placeholder": "PlayerName or @a",
                "source": "players",
            },
        ],
    },
    {
        "id": "weather",
        "label": "Change weather",
        "root": "weather",
        "category": "World",
        "description": "Set clear, rainy, or thunder weather.",
        "safety": "normal",
        "arguments": [
            {
                "key": "weather",
                "label": "Weather",
                "kind": "choice",
                "required": True,
                "options": ["clear", "rain", "thunder"],
            },
            {
                "key": "duration",
                "label": "Duration in seconds",
                "kind": "integer",
                "required": False,
                "minimum": 1,
                "maximum": 1_000_000,
            },
        ],
    },
    {
        "id": "time_set",
        "label": "Set the time",
        "root": "time set",
        "category": "World",
        "description": "Set the current world's time of day.",
        "safety": "normal",
        "arguments": [
            {
                "key": "time",
                "label": "Time",
                "kind": "choice",
                "required": True,
                "options": ["day", "noon", "night", "midnight"],
            },
        ],
    },
    {
        "id": "difficulty",
        "label": "Set difficulty",
        "root": "difficulty",
        "category": "World",
        "description": "Change the world's gameplay difficulty.",
        "safety": "caution",
        "arguments": [
            {
                "key": "difficulty",
                "label": "Difficulty",
                "kind": "choice",
                "required": True,
                "options": ["peaceful", "easy", "normal", "hard"],
            },
        ],
    },
    {
        "id": "kick",
        "label": "Kick a player",
        "root": "kick",
        "category": "Moderation",
        "description": "Disconnect a player, optionally showing them a reason.",
        "safety": "danger",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
            {
                "key": "reason",
                "label": "Reason",
                "kind": "text",
                "required": False,
                "placeholder": "Please rejoin later",
                "max_length": 160,
            },
        ],
    },
    {
        "id": "ban",
        "label": "Ban a player",
        "root": "ban",
        "category": "Moderation",
        "description": "Ban a player from joining this server.",
        "safety": "danger",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
            {
                "key": "reason",
                "label": "Reason",
                "kind": "text",
                "required": False,
                "placeholder": "Banned by an operator",
                "max_length": 160,
            },
        ],
    },
    {
        "id": "pardon",
        "label": "Pardon a player",
        "root": "pardon",
        "category": "Moderation",
        "description": "Remove a player's server ban.",
        "safety": "caution",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
        ],
    },
    {
        "id": "whitelist_add",
        "label": "Add to allowlist",
        "root": "whitelist add",
        "category": "Moderation",
        "description": "Allow a player to join when the allowlist is enabled.",
        "safety": "normal",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
        ],
    },
    {
        "id": "whitelist_remove",
        "label": "Remove from allowlist",
        "root": "whitelist remove",
        "category": "Moderation",
        "description": "Remove a player from the server allowlist.",
        "safety": "caution",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
        ],
    },
    {
        "id": "op",
        "label": "Make an operator",
        "root": "op",
        "category": "Moderation",
        "description": "Grant a player full server operator privileges.",
        "safety": "danger",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
        ],
    },
    {
        "id": "deop",
        "label": "Remove operator",
        "root": "deop",
        "category": "Moderation",
        "description": "Remove a player's server operator privileges.",
        "safety": "caution",
        "arguments": [
            {
                "key": "target",
                "label": "Player",
                "kind": "player",
                "required": True,
                "placeholder": "PlayerName",
                "source": "players",
                "allow_selectors": False,
            },
        ],
    },
    {
        "id": "save_all",
        "label": "Save the world",
        "root": "save-all flush",
        "category": "Server",
        "description": "Write pending world changes to disk immediately.",
        "safety": "normal",
        "arguments": [],
    },
)


def catalog_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "revision": "curated-1",
        "source": "curated",
        "complete": False,
        "commands": list(COMMANDS),
    }


def _value_text(value: str | int | bool) -> str:
    return str(value).strip()


def render_guided_command(
    command_id: str, values: dict[str, str | int | bool]
) -> tuple[str, Safety]:
    command = next((entry for entry in COMMANDS if entry["id"] == command_id), None)
    if command is None:
        raise ValueError("That guided command is not in this catalog.")
    arguments = command["arguments"]
    assert isinstance(arguments, list)
    allowed_keys = {str(argument["key"]) for argument in arguments}
    if set(values) - allowed_keys:
        raise ValueError("The guided command contains an unexpected value.")

    parts = str(command["root"]).split()
    missing_optional = False
    for argument in arguments:
        key = str(argument["key"])
        required = bool(argument.get("required"))
        raw = values.get(key, "")
        text = _value_text(raw)
        if not text:
            if required:
                raise ValueError(f"Choose {str(argument['label']).lower()} before sending.")
            missing_optional = True
            continue
        if missing_optional:
            raise ValueError("Fill optional command values from left to right.")
        if any(character in text for character in "\r\n\x00"):
            raise ValueError("Command values must fit on one line.")

        kind = argument["kind"]
        if kind == "integer":
            try:
                number = int(text)
            except ValueError as exc:
                raise ValueError(f"{argument['label']} must be a whole number.") from exc
            minimum = argument.get("minimum")
            maximum = argument.get("maximum")
            if isinstance(minimum, int) and number < minimum:
                raise ValueError(f"{argument['label']} must be at least {minimum}.")
            if isinstance(maximum, int) and number > maximum:
                raise ValueError(f"{argument['label']} must be at most {maximum}.")
            text = str(number)
        elif kind == "choice":
            options = argument.get("options", [])
            if text not in options:
                raise ValueError(f"Choose a listed value for {str(argument['label']).lower()}.")
        elif kind == "boolean":
            if text not in {"true", "false"}:
                raise ValueError(f"{argument['label']} must be true or false.")
        elif kind == "player":
            valid_name = re.fullmatch(r"[A-Za-z0-9_]{3,16}", text) is not None
            allow_selectors = bool(argument.get("allow_selectors", True))
            valid_selector = allow_selectors and text in {"@a", "@e", "@p", "@r", "@s"}
            if not valid_name and not valid_selector:
                raise ValueError("Use a 3–16 character player name or an available selector.")
        elif kind == "resource":
            if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", text) is None:
                raise ValueError("Use an item identifier such as minecraft:diamond.")
        elif kind == "text":
            maximum = argument.get("max_length", 256)
            if not isinstance(maximum, int) or len(text) > maximum:
                raise ValueError(f"{argument['label']} is too long.")
        parts.append(text)

    safety = cast(Safety, command["safety"])
    if safety not in {"normal", "caution", "danger"}:
        raise RuntimeError("The guided command catalog contains an invalid safety level.")
    return " ".join(parts), safety
