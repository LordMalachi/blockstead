from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from blockstead.db import Base, create_session_factory
from blockstead.models import PlayerSession, Profile
from blockstead.player_sessions import (
    JOIN_PATTERN,
    LEAVE_PATTERN,
    record_log_line,
    summarize_sessions,
)


def _db(tmp_path: Path) -> Session:
    factory = create_session_factory(tmp_path / "blockstead.db")
    Base.metadata.create_all(factory.kw["bind"])
    db = factory()
    db.add(Profile(id="p1", name="Test", server_directory=str(tmp_path), distribution="vanilla"))
    db.add(
        Profile(
            id="p2", name="Other", server_directory=str(tmp_path / "other"), distribution="vanilla"
        )
    )
    db.commit()
    return db


def test_join_pattern_matches_with_and_without_timestamp_prefix() -> None:
    assert JOIN_PATTERN.search("Steve joined the game")
    assert JOIN_PATTERN.search("[12:34:56] [Server thread/INFO]: Steve joined the game")
    assert not JOIN_PATTERN.search("Steve left the game")


def test_leave_pattern_matches_with_and_without_timestamp_prefix() -> None:
    assert LEAVE_PATTERN.search("Steve left the game")
    assert LEAVE_PATTERN.search("[12:34:56] [Server thread/INFO]: Steve left the game")
    assert not LEAVE_PATTERN.search("Steve joined the game")


def test_record_log_line_ignores_unrelated_lines(tmp_path: Path) -> None:
    db = _db(tmp_path)
    record_log_line(db, "p1", "Done (0.123s)! For help, type \"help\"", datetime.now(UTC))
    db.commit()
    assert db.scalars(select(PlayerSession)).all() == []


def test_join_creates_an_open_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    now = datetime.now(UTC)
    record_log_line(db, "p1", "Steve joined the game", now)
    db.commit()
    rows = db.scalars(select(PlayerSession)).all()
    assert len(rows) == 1
    assert rows[0].player_name == "Steve"
    assert rows[0].profile_id == "p1"
    assert rows[0].left_at is None


def test_duplicate_join_does_not_create_a_second_open_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    now = datetime.now(UTC)
    record_log_line(db, "p1", "Steve joined the game", now)
    db.commit()
    record_log_line(db, "p1", "Steve joined the game", now + timedelta(seconds=5))
    db.commit()
    rows = db.scalars(select(PlayerSession)).all()
    assert len(rows) == 1


def test_leave_closes_the_open_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    joined = datetime.now(UTC)
    record_log_line(db, "p1", "Steve joined the game", joined)
    db.commit()
    left = joined + timedelta(minutes=10)
    record_log_line(db, "p1", "Steve left the game", left)
    db.commit()
    row = db.scalar(select(PlayerSession))
    assert row is not None
    assert row.left_at is not None


def test_leave_without_a_prior_join_does_nothing(tmp_path: Path) -> None:
    db = _db(tmp_path)
    record_log_line(db, "p1", "Steve left the game", datetime.now(UTC))
    db.commit()
    assert db.scalars(select(PlayerSession)).all() == []


def test_sessions_are_scoped_per_profile(tmp_path: Path) -> None:
    db = _db(tmp_path)
    now = datetime.now(UTC)
    record_log_line(db, "p1", "Steve joined the game", now)
    db.commit()
    # A leave line arriving for a different profile must not close p1's session:
    # Blockstead only ever manages one process at a time, but log events still
    # carry the profile that produced them.
    record_log_line(db, "p2", "Steve left the game", now + timedelta(seconds=5))
    db.commit()
    row = db.scalar(select(PlayerSession).where(PlayerSession.profile_id == "p1"))
    assert row is not None
    assert row.left_at is None


def test_summarize_sessions_reports_open_session_as_tracked_online(tmp_path: Path) -> None:
    db = _db(tmp_path)
    joined = datetime.now(UTC) - timedelta(seconds=30)
    record_log_line(db, "p1", "Steve joined the game", joined)
    db.commit()
    summary = summarize_sessions(db, "p1", ["Steve"], datetime.now(UTC))
    assert summary["Steve"].tracked_online is True
    assert summary["Steve"].last_seen is None
    assert summary["Steve"].session_seconds is not None
    assert summary["Steve"].session_seconds >= 29


def test_summarize_sessions_reports_closed_session_last_seen_and_duration(tmp_path: Path) -> None:
    db = _db(tmp_path)
    joined = datetime.now(UTC) - timedelta(minutes=5)
    left = joined + timedelta(minutes=2)
    record_log_line(db, "p1", "Steve joined the game", joined)
    db.commit()
    record_log_line(db, "p1", "Steve left the game", left)
    db.commit()
    summary = summarize_sessions(db, "p1", ["Steve"], datetime.now(UTC))
    assert summary["Steve"].tracked_online is False
    assert summary["Steve"].last_seen is not None
    assert summary["Steve"].session_seconds == 120


def test_summarize_sessions_reports_unknown_for_a_never_seen_player(tmp_path: Path) -> None:
    db = _db(tmp_path)
    summary = summarize_sessions(db, "p1", ["NeverJoined"], datetime.now(UTC))
    assert summary["NeverJoined"].tracked_online is False
    assert summary["NeverJoined"].last_seen is None
    assert summary["NeverJoined"].session_seconds is None


def test_summarize_sessions_uses_the_most_recent_session(tmp_path: Path) -> None:
    db = _db(tmp_path)
    first_join = datetime.now(UTC) - timedelta(hours=2)
    first_leave = first_join + timedelta(minutes=1)
    record_log_line(db, "p1", "Steve joined the game", first_join)
    db.commit()
    record_log_line(db, "p1", "Steve left the game", first_leave)
    db.commit()
    second_join = datetime.now(UTC) - timedelta(minutes=10)
    second_leave = second_join + timedelta(minutes=3)
    record_log_line(db, "p1", "Steve joined the game", second_join)
    db.commit()
    record_log_line(db, "p1", "Steve left the game", second_leave)
    db.commit()
    summary = summarize_sessions(db, "p1", ["Steve"], datetime.now(UTC))
    assert summary["Steve"].session_seconds == 180


def test_summarize_sessions_with_no_names_returns_empty(tmp_path: Path) -> None:
    db = _db(tmp_path)
    assert summarize_sessions(db, "p1", [], datetime.now(UTC)) == {}
