import asyncio
from datetime import UTC, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

from sqlalchemy import select

from blockstead.db import Base, create_session_factory
from blockstead.models import (
    Administrator,
    AutomationEvent,
    AutomationRun,
    BackupRecord,
    Profile,
    Schedule,
)
from blockstead.scheduler import Scheduler, next_executions


def test_close_tolerates_completed_task_from_closed_loop() -> None:
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(0))
    loop.run_until_complete(task)
    loop.close()

    scheduler = Scheduler.__new__(Scheduler)
    scheduler._task = task
    asyncio.run(scheduler.close())

    assert scheduler._task is None


def test_scheduled_stop_records_backup_and_restores_saving(tmp_path: Path) -> None:
    server = tmp_path / "server"
    (server / "world").mkdir(parents=True)
    (server / "world" / "level.dat").write_bytes(b"world")
    factory = create_session_factory(tmp_path / "blockstead.db")
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        admin = Administrator(username="owner", password_hash="unused")  # noqa: S106
        profile = Profile(
            name="Home",
            server_directory=str(server),
            distribution="vanilla",
            minecraft_version="1.21.8",
        )
        db.add_all([admin, profile])
        db.flush()
        db.add(
            Schedule(
                profile_id=profile.id,
                stop_time="12:00",
                backup_before_stop=True,
            )
        )
        db.commit()

    manager = Mock()
    manager.snapshot.return_value = {"state": "RUNNING"}
    manager.command = AsyncMock()
    manager.stop = AsyncMock(return_value=True)
    scheduler = Scheduler(factory, manager, AsyncMock(), tmp_path / "data", tmp_path)

    asyncio.run(
        scheduler.tick(datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc))  # noqa: UP017
    )

    manager.command.assert_has_awaits(
        [
            call("say Server maintenance is starting now."),
            call("save-off"),
            call("save-all flush"),
            call("save-on"),
        ]
    )
    manager.stop.assert_awaited_once_with(timeout=60.0)
    with factory() as db:
        record = db.scalar(select(BackupRecord))
        assert record is not None
        assert record.status == "completed"
        assert record.trigger == "schedule"
        assert record.size_bytes is not None and record.size_bytes > 0
        run = db.scalar(select(AutomationRun))
        assert run is not None
        assert run.status == "success"
        assert run.action == "maintenance"


def test_weekday_filter_and_next_three_preview(tmp_path: Path) -> None:
    schedule = Schedule(
        profile_id="profile",
        enabled=True,
        start_time="09:00",
        stop_time="22:00",
        weekdays="0,2,4",
        backup_before_stop=True,
    )
    event = AutomationEvent(profile_id="profile", run_at="2026-07-21T18:00")
    now = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)  # Monday

    upcoming = next_executions(schedule, [event], now)

    assert [item["label"] for item in upcoming] == [
        "Start server",
        "Maintenance stop",
        "One-time maintenance",
    ]
    assert upcoming[0]["at"] == "2026-07-20T09:00:00+00:00"

    weekly = Schedule(
        profile_id="weekly",
        enabled=True,
        stop_time="07:00",
        weekdays="0",
        backup_before_stop=False,
    )
    weekly_upcoming = next_executions(weekly, [], now)
    assert len(weekly_upcoming) == 3
    assert weekly_upcoming[-1]["at"] == "2026-08-10T07:00:00+00:00"


def test_only_when_empty_skips_when_status_is_unavailable(tmp_path: Path) -> None:
    factory = create_session_factory(tmp_path / "blockstead.db")
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        admin = Administrator(username="owner", password_hash="unused")  # noqa: S106
        profile = Profile(
            name="Home",
            server_directory=str(tmp_path),
            distribution="vanilla",
            minecraft_version="1.21.8",
        )
        db.add_all([admin, profile])
        db.flush()
        profile_id = profile.id
        db.add(
            Schedule(
                profile_id=profile.id,
                stop_time="12:00",
                backup_before_stop=False,
                only_when_empty=True,
            )
        )
        db.commit()

    manager = Mock()
    manager.snapshot.return_value = {"state": "RUNNING", "profile_id": profile_id}
    manager.command = AsyncMock()
    manager.stop = AsyncMock(return_value=True)
    scheduler = Scheduler(factory, manager, AsyncMock(), tmp_path / "data", tmp_path)
    scheduler._online_players = AsyncMock(return_value=None)  # type: ignore[method-assign]

    asyncio.run(
        scheduler.tick(datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc))  # noqa: UP017
    )

    manager.command.assert_not_awaited()
    manager.stop.assert_not_awaited()
    with factory() as db:
        run = db.scalar(select(AutomationRun))
        assert run is not None
        assert run.status == "skipped"
        assert "unavailable" in run.detail
