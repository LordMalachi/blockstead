import asyncio
import shutil
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .models import AuditEvent, Profile, Schedule
from .process import ProcessManager


class Scheduler:
    """Small persistent daily scheduler. All server operations remain in the API process."""

    def __init__(self, factory: sessionmaker[Session], manager: ProcessManager, start: Callable[[Profile], Awaitable[None]], data_dir: Path) -> None:
        self.factory, self.manager, self.start, self.data_dir = factory, manager, start, data_dir
        self._task: asyncio.Task[None] | None = None

    def begin(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                # A bad profile or unavailable disk must not stop future schedules.
                pass
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

    async def _start(self, db: Session, schedule: Schedule, profile: Profile, date: str) -> None:
        if self.manager.snapshot()["state"] == "STOPPED":
            await self.start(profile)
            db.add(AuditEvent(admin_id=self._admin_id(db), category="scheduled_start", result="success", safe_detail=f"Started {profile.name} on schedule"))
        schedule.last_start_date = date

    async def _stop(self, db: Session, schedule: Schedule, profile: Profile, date: str, now: datetime) -> None:
        if self.manager.snapshot()["state"] in {"RUNNING", "STARTING", "DEGRADED"}:
            if schedule.backup_before_stop:
                await self.manager.command("save-all flush")
                self.backup(profile, now)
            graceful = await self.manager.stop(timeout=60.0)
            if not graceful:
                raise RuntimeError("scheduled graceful stop timed out")
            db.add(AuditEvent(admin_id=self._admin_id(db), category="scheduled_stop", result="success", safe_detail=f"Backed up and stopped {profile.name} on schedule"))
        schedule.last_stop_date = date
        # The installer grants this exact helper passwordless access. It sets the RTC
        # wake alarm before requesting shutdown; failures leave the machine on.
        if schedule.power_off_after_stop:
            command = ["sudo", "-n", "/usr/lib/blockstead/blockstead-power", "poweroff"]
            if schedule.wake_time:
                tomorrow = (now + timedelta(days=1)).date().isoformat()
                command += ["--wake", f"{tomorrow}T{schedule.wake_time}:00"]
            process = await asyncio.create_subprocess_exec(*command)
            await process.wait()

    def backup(self, profile: Profile, now: datetime) -> Path:
        # Ask Minecraft to flush first; archive world folders without ever including secrets.
        destination = self.data_dir / "backups"
        destination.mkdir(mode=0o700, exist_ok=True)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        archive = destination / f"{profile.id}-{stamp}"
        roots = [path for path in Path(profile.server_directory).glob("world*") if path.is_dir()]
        if not roots:
            raise RuntimeError("No world directory was found for backup")
        for root in roots:
            shutil.make_archive(str(archive) + f"-{root.name}", "gztar", root_dir=root.parent, base_dir=root.name)
        return archive

    @staticmethod
    def _admin_id(db: Session) -> str:
        # Schedules have no interactive actor. Attribute execution to the first owner.
        from .models import Administrator
        return db.scalars(select(Administrator.id)).first() or "system"
