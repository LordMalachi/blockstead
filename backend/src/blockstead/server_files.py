import json
from pathlib import Path

from pydantic import BaseModel

from .server_settings import MAX_FILE_BYTES as MAX_FILE_BYTES
from .server_settings import read_settings as read_settings


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
