import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .backups import BackupError, create_backup_archive
from .import_scan import canonical_child
from .models import AuditEvent, BackupRecord, Profile, Schedule
from .process import ProcessManager
from .retention import enforce_retention

logger = logging.getLogger(__name__)


class Scheduler:
    """Small persistent daily scheduler. All server operations remain in the API process."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        manager: ProcessManager,
        start: Callable[[Profile], Awaitable[None]],
        data_dir: Path,
        server_root: Path,
    ) -> None:
        self.factory, self.manager, self.start = factory, manager, start
        self.data_dir, self.server_root = data_dir, server_root
        self._task: asyncio.Task[None] | None = None

    def begin(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        task, self._task = self._task, None
        if task is None or task.get_loop().is_closed():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                # A bad profile or unavailable disk must not stop future schedules.
                logger.exception("Scheduled server operation failed")
            await asyncio.sleep(30)

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        date, clock = now.date().isoformat(), now.strftime("%H:%M")
        with self.factory() as db:
            schedules = db.scalars(select(Schedule).where(Schedule.enabled.is_(True))).all()
            for schedule in schedules:
                profile = db.get(Profile, schedule.profile_id)
                if not profile:
                    continue
                if schedule.start_time == clock and schedule.last_start_date != date:
                    await self._start(db, schedule, profile, date)
                if schedule.stop_time == clock and schedule.last_stop_date != date:
                    await self._stop(db, schedule, profile, date, now)
            db.commit()

    async def _start(
        self, db: Session, schedule: Schedule, profile: Profile, date: str
    ) -> None:
        if self.manager.snapshot()["state"] == "STOPPED":
            await self.start(profile)
            db.add(
                AuditEvent(
                    admin_id=self._admin_id(db),
                    category="scheduled_start",
                    result="success",
                    safe_detail=f"Started {profile.name} on schedule",
                )
            )
        schedule.last_start_date = date

    async def _stop(
        self,
        db: Session,
        schedule: Schedule,
        profile: Profile,
        date: str,
        now: datetime,
    ) -> None:
        schedule.last_stop_date = date
        if self.manager.snapshot()["state"] in {"RUNNING", "STARTING", "DEGRADED"}:
            backed_up = False
            if schedule.backup_before_stop:
                saving_suspended = False
                try:
                    await self.manager.command("save-off")
                    saving_suspended = True
                    await self.manager.command("save-all flush")
                    await self.backup(db, profile, now)
                    backed_up = True
                finally:
                    if saving_suspended:
                        await self.manager.command("save-on")
            graceful = await self.manager.stop(timeout=60.0)
            if not graceful:
                raise RuntimeError("scheduled graceful stop timed out")
            db.add(
                AuditEvent(
                    admin_id=self._admin_id(db),
                    category="scheduled_stop",
                    result="success",
                    safe_detail=(
                        f"Backed up and stopped {profile.name} on schedule"
                        if backed_up
                        else f"Stopped {profile.name} on schedule"
                    ),
                )
            )
        # The installer grants this exact helper passwordless access. It sets the RTC
        # wake alarm before requesting shutdown; failures leave the machine on.
        if schedule.power_off_after_stop:
            command = ["sudo", "-n", "/usr/lib/blockstead/blockstead-power", "poweroff"]
            if schedule.wake_time:
                tomorrow = (now + timedelta(days=1)).date().isoformat()
                command += ["--wake", f"{tomorrow}T{schedule.wake_time}:00"]
            process = await asyncio.create_subprocess_exec(*command)
            await process.wait()

    async def backup(self, db: Session, profile: Profile, now: datetime) -> BackupRecord:
        record = BackupRecord(profile_id=profile.id, trigger="schedule", created_at=now)
        db.add(record)
        db.flush()
        # Make progress visible to the Backup Center and block a simultaneous
        # manual backup before the archive work moves to a thread.
        db.commit()
        started = time.monotonic()
        try:
            try:
                server_directory = canonical_child(
                    Path(profile.server_directory), self.server_root
                )
            except (ValueError, OSError) as exc:
                raise BackupError(
                    "The profile folder is no longer inside the allowed server root."
                ) from exc
            archive = await asyncio.to_thread(
                create_backup_archive,
                profile.id,
                server_directory,
                self.data_dir,
                record.id,
                now,
                profile_name=profile.name,
                distribution=profile.distribution,
                minecraft_version=profile.minecraft_version,
                application_version=__version__,
                trigger="schedule",
            )
        except BackupError as exc:
            record.status = "failed"
            record.result = str(exc)
            record.completed_at = datetime.now().astimezone()
            record.duration_ms = round((time.monotonic() - started) * 1000)
            db.add(
                AuditEvent(
                    admin_id=self._admin_id(db),
                    category="scheduled_backup",
                    result="failed",
                    safe_detail=f"Backup failed for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise

        record.status = "completed"
        record.file_name = archive.file_name
        record.manifest_name = archive.manifest_name
        record.sha256 = archive.sha256
        record.included_paths = json.dumps(list(archive.included_paths))
        record.size_bytes = archive.size_bytes
        record.duration_ms = round((time.monotonic() - started) * 1000)
        record.result = f"Protected {', '.join(archive.included_paths)}."
        record.completed_at = datetime.now().astimezone()
        enforce_retention(db, profile, self.data_dir)
        db.add(
            AuditEvent(
                admin_id=self._admin_id(db),
                category="scheduled_backup",
                result="success",
                safe_detail=f"Created scheduled backup for {profile.name}",
            )
        )
        db.commit()
        return record

    @staticmethod
    def _admin_id(db: Session) -> str:
        # Schedules have no interactive actor. Attribute execution to the first owner.
        from .models import Administrator

        return db.scalars(select(Administrator.id)).first() or "system"
