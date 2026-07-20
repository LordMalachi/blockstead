from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select

from blockstead.cli import PasswordResetError, reset_administrator_password
from blockstead.db import Base, create_session_factory
from blockstead.models import Administrator, AuditEvent, LoginSession
from blockstead.security import digest, hash_password, verify_password


def recovery_database(tmp_path: Path) -> tuple[Path, str]:
    database = tmp_path / "blockstead.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()

    factory = create_session_factory(database)
    with factory.begin() as db:
        administrator = Administrator(
            username="owner", password_hash=hash_password("correct horse battery staple")
        )
        db.add(administrator)
        db.flush()
        db.add(
            LoginSession(
                admin_id=administrator.id,
                token_hash=digest("old browser token"),
                csrf_hash=digest("old csrf token"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),  # noqa: UP017
            )
        )
        administrator_id = administrator.id
    return database, administrator_id


def test_password_recovery_replaces_hash_and_revokes_sessions(tmp_path: Path) -> None:
    database, administrator_id = recovery_database(tmp_path)

    username = reset_administrator_password(database, "an entirely new password")

    factory = create_session_factory(database)
    with factory() as db:
        administrator = db.get(Administrator, administrator_id)
        assert administrator is not None
        assert username == "owner"
        assert verify_password(administrator.password_hash, "an entirely new password")
        assert not verify_password(administrator.password_hash, "correct horse battery staple")
        assert (db.scalar(select(func.count()).select_from(LoginSession)) or 0) == 0
        event = db.scalar(select(AuditEvent).order_by(AuditEvent.created_at.desc()))
        assert event is not None
        assert event.category == "security"
        assert event.safe_detail == "Administrator password reset from the local system."
        assert "an entirely new password" not in event.safe_detail


def test_password_recovery_rejects_short_password_without_changing_data(tmp_path: Path) -> None:
    database, administrator_id = recovery_database(tmp_path)

    try:
        reset_administrator_password(database, "too short")
    except PasswordResetError as exc:
        assert "at least 12 characters" in str(exc)
    else:
        raise AssertionError("short password was accepted")

    factory = create_session_factory(database)
    with factory() as db:
        administrator = db.get(Administrator, administrator_id)
        assert administrator is not None
        assert verify_password(administrator.password_hash, "correct horse battery staple")
        assert (db.scalar(select(func.count()).select_from(LoginSession)) or 0) == 1


def test_password_recovery_refuses_a_missing_database(tmp_path: Path) -> None:
    try:
        reset_administrator_password(tmp_path / "missing.db", "an entirely new password")
    except PasswordResetError as exc:
        assert "No Blockstead database" in str(exc)
    else:
        raise AssertionError("missing database was accepted")


def test_password_recovery_reports_a_damaged_database_safely(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    database.write_text("this is not a sqlite database", encoding="utf-8")

    with pytest.raises(PasswordResetError) as failure:
        reset_administrator_password(database, "an entirely new password")

    message = str(failure.value)
    assert "could not be updated" in message
    assert "sudo blockstead doctor" in message
    assert "not a database" not in message
