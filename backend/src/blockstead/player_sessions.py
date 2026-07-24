"""Best-effort player join/leave tracking parsed from the managed server's log.

Only recognized log phrasing produces a session. A modded server or a
different server locale simply has no session history for that profile —
Blockstead never guesses a join or leave time it did not observe.
"""

import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .activity import utc_timestamp
from .models import PlayerSession

#: Vanilla's own English log phrasing: "<name> joined the game" / "<name> left
#: the game", with or without a leading timestamp/thread prefix.
JOIN_PATTERN = re.compile(r"([A-Za-z0-9_]{1,16}) joined the game$")
LEAVE_PATTERN = re.compile(r"([A-Za-z0-9_]{1,16}) left the game$")
_STALE_SESSION_DAYS = 30


class PlayerSessionInfo(BaseModel):
    player_name: str
    #: An open session exists for this player. Best-effort: a Blockstead
    #: restart mid-session, or an unrecognized leave line, can leave this
    #: stuck on even after the player disconnects.
    tracked_online: bool
    last_seen: str | None
    session_seconds: int | None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)  # noqa: UP017


def _open_session(db: Session, profile_id: str, player_name: str) -> PlayerSession | None:
    return db.scalar(
        select(PlayerSession)
        .where(
            PlayerSession.profile_id == profile_id,
            PlayerSession.player_name == player_name,
            PlayerSession.left_at.is_(None),
        )
        .order_by(PlayerSession.joined_at.desc())
    )


def _prune_stale_sessions(db: Session, now: datetime) -> None:
    cutoff = now - timedelta(days=_STALE_SESSION_DAYS)
    db.execute(
        delete(PlayerSession).where(
            PlayerSession.left_at.is_not(None), PlayerSession.left_at < cutoff
        )
    )


def record_log_line(db: Session, profile_id: str, line: str, now: datetime) -> None:
    """Parse one server log line and update session history if it matches."""

    join = JOIN_PATTERN.search(line)
    if join:
        player_name = join.group(1)
        if _open_session(db, profile_id, player_name) is None:
            db.add(PlayerSession(profile_id=profile_id, player_name=player_name, joined_at=now))
            _prune_stale_sessions(db, now)
        return
    leave = LEAVE_PATTERN.search(line)
    if leave:
        session = _open_session(db, profile_id, leave.group(1))
        if session is not None:
            session.left_at = now


def summarize_sessions(
    db: Session, profile_id: str, player_names: Iterable[str], now: datetime
) -> dict[str, PlayerSessionInfo]:
    """The most recent session (open or closed) for each requested player."""

    names = list(dict.fromkeys(player_names))
    if not names:
        return {}
    rows = db.scalars(
        select(PlayerSession)
        .where(PlayerSession.profile_id == profile_id, PlayerSession.player_name.in_(names))
        .order_by(PlayerSession.joined_at.desc())
    ).all()
    latest: dict[str, PlayerSession] = {}
    for row in rows:
        latest.setdefault(row.player_name, row)
    result: dict[str, PlayerSessionInfo] = {}
    for name in names:
        session = latest.get(name)
        if session is None:
            result[name] = PlayerSessionInfo(
                player_name=name, tracked_online=False, last_seen=None, session_seconds=None
            )
            continue
        joined_at = _aware(session.joined_at)
        if session.left_at is None:
            duration = max(0, int((now - joined_at).total_seconds()))
            result[name] = PlayerSessionInfo(
                player_name=name, tracked_online=True, last_seen=None, session_seconds=duration
            )
        else:
            left_at = _aware(session.left_at)
            duration = max(0, int((left_at - joined_at).total_seconds()))
            result[name] = PlayerSessionInfo(
                player_name=name,
                tracked_online=False,
                last_seen=utc_timestamp(left_at),
                session_seconds=duration,
            )
    return result
