import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

MAX_FILE_BYTES = 1_000_000

SettingType = Literal["string", "integer", "boolean"]

KNOWN_SETTINGS: dict[str, tuple[SettingType, str]] = {
    "motd": ("string", "Message of the day"),
    "server-port": ("integer", "Server port"),
    "max-players": ("integer", "Player limit"),
    "online-mode": ("boolean", "Verify Mojang accounts"),
    "white-list": ("boolean", "Allowlist required"),
    "enforce-whitelist": ("boolean", "Enforce allowlist"),
    "pvp": ("boolean", "Player-versus-player combat"),
    "difficulty": ("string", "Difficulty"),
    "gamemode": ("string", "Default game mode"),
    "hardcore": ("boolean", "Hardcore mode"),
    "level-name": ("string", "World folder"),
    "view-distance": ("integer", "View distance (chunks)"),
    "simulation-distance": ("integer", "Simulation distance (chunks)"),
    "spawn-protection": ("integer", "Spawn protection radius"),
    "allow-flight": ("boolean", "Allow flight"),
    "allow-nether": ("boolean", "Allow the Nether"),
    "enable-command-block": ("boolean", "Command blocks"),
}

SECRET_MARKERS = ("password", "secret", "token")


class SettingEntry(BaseModel):
    key: str
    label: str
    type: SettingType
    value: str | int | bool | None


class SettingsView(BaseModel):
    present: bool
    settings: list[SettingEntry]
    other_keys: list[str]


class PlayerEntry(BaseModel):
    name: str
    uuid: str | None = None
    level: int | None = None
    reason: str | None = None


class PlayerFile(BaseModel):
    present: bool
    readable: bool
    players: list[PlayerEntry]


class PlayersView(BaseModel):
    allowlist: PlayerFile
    operators: PlayerFile
    bans: PlayerFile


def _read_limited(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _typed_value(kind: SettingType, raw: str) -> str | int | bool | None:
    if kind == "boolean":
        return raw.lower() == "true" if raw.lower() in {"true", "false"} else None
    if kind == "integer":
        try:
            return int(raw)
        except ValueError:
            return None
    return raw


def read_settings(server_directory: Path) -> SettingsView:
    text = _read_limited(server_directory / "server.properties")
    if text is None:
        return SettingsView(present=False, settings=[], other_keys=[])
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        values[key.strip()] = raw.strip()
    settings = [
        SettingEntry(key=key, label=label, type=kind, value=_typed_value(kind, values[key]))
        for key, (kind, label) in KNOWN_SETTINGS.items()
        if key in values
    ]
    other = sorted(
        key
        for key in values
        if key not in KNOWN_SETTINGS
        and not any(marker in key.lower() for marker in SECRET_MARKERS)
    )
    return SettingsView(present=True, settings=settings, other_keys=other)


def _read_player_file(path: Path, *, ban_file: bool = False) -> PlayerFile:
    if not path.is_file():
        return PlayerFile(present=False, readable=False, players=[])
    text = _read_limited(path)
    if text is None:
        return PlayerFile(present=True, readable=False, players=[])
    try:
        records = json.loads(text)
    except json.JSONDecodeError:
        return PlayerFile(present=True, readable=False, players=[])
    if not isinstance(records, list):
        return PlayerFile(present=True, readable=False, players=[])
    players = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            continue
        uuid = record.get("uuid")
        level = record.get("level")
        reason = record.get("reason") if ban_file else None
        players.append(
            PlayerEntry(
                name=record["name"][:64],
                uuid=uuid if isinstance(uuid, str) else None,
                level=level if isinstance(level, int) else None,
                reason=reason[:200] if isinstance(reason, str) else None,
            )
        )
    return PlayerFile(present=True, readable=True, players=players)


def read_players(server_directory: Path) -> PlayersView:
    return PlayersView(
        allowlist=_read_player_file(server_directory / "whitelist.json"),
        operators=_read_player_file(server_directory / "ops.json"),
        bans=_read_player_file(server_directory / "banned-players.json", ban_file=True),
    )
