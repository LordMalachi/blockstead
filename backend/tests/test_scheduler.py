import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call

from sqlalchemy import select

from blockstead.db import Base, create_session_factory
from blockstead.models import Administrator, BackupRecord, Profile, Schedule
from blockstead.scheduler import Scheduler


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
        [call("save-off"), call("save-all flush"), call("save-on")]
    )
    manager.stop.assert_awaited_once_with(timeout=60.0)
    with factory() as db:
        record = db.scalar(select(BackupRecord))
        assert record is not None
        assert record.status == "completed"
        assert record.trigger == "schedule"
        assert record.size_bytes is not None and record.size_bytes > 0
