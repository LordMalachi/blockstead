import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from . import __version__
from .backups import BackupError, create_backup_archive, mirror_backup_archive
from .import_scan import canonical_child
from .models import (
    Administrator,
    AuditEvent,
    AutomationEvent,
    AutomationRun,
    BackupRecord,
    Profile,
    Schedule,
)
from .overview import minecraft_status, read_properties
from .process import ProcessManager
from .retention import enforce_retention

logger = logging.getLogger(__name__)

WEEKDAY_LABELS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
POWER_HELPER = Path("/usr/lib/blockstead/blockstead-power")


def parse_weekdays(value: str) -> list[int]:
    try:
        days = sorted({int(item) for item in value.split(",") if item != ""})
    except ValueError:
        return list(range(7))
    return days if days and all(0 <= day <= 6 for day in days) else list(range(7))


def automation_steps(backup: bool, power_off: bool) -> list[str]:
    steps = ["Announce maintenance", "Flush Minecraft saves"]
    if backup:
        steps.append("Create a verified backup")
    steps.append("Stop the server safely")
    if power_off:
        steps.append("Shut down the Linux host")
    return steps


def next_executions(
    schedule: Schedule | None,
    events: Sequence[AutomationEvent],
    now: datetime,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return the next local-time actions from recurring and one-time plans."""

    candidates: list[tuple[datetime, dict[str, object]]] = []
    if schedule and schedule.enabled:
        weekdays = set(parse_weekdays(schedule.weekdays))
        # Twenty-two days guarantees three future executions for a once-weekly plan.
        for offset in range(22):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() not in weekdays:
                continue
            for action, label, clock in (
                ("start", "Start server", schedule.start_time),
                ("maintenance", "Maintenance stop", schedule.stop_time),
            ):
                if not clock:
                    continue
                hour, minute = (int(part) for part in clock.split(":"))
                when = now.replace(
                    year=day.year,
                    month=day.month,
                    day=day.day,
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )
                if when <= now:
                    continue
                steps = ["Start the server"] if action == "start" else automation_steps(
                    schedule.backup_before_stop, schedule.power_off_after_stop
                )
                candidates.append(
                    (
                        when,
                        {
                            "kind": "recurring",
                            "action": action,
                            "label": label,
                            "at": when.isoformat(),
                            "steps": steps,
                        },
                    )
                )
    for event in events:
        if event.completed_at is not None:
            continue
        try:
            naive = datetime.strptime(event.run_at, "%Y-%m-%dT%H:%M")
        except ValueError:
            continue
        when = naive.replace(tzinfo=now.tzinfo)
        if when <= now:
            continue
        candidates.append(
            (
                when,
                {
                    "kind": "one_time",
                    "action": "maintenance",
                    "label": "One-time maintenance",
                    "at": when.isoformat(),
                    "steps": automation_steps(
                        event.backup_before_stop, event.power_off_after_stop
                    ),
                },
            )
        )
    candidates.sort(key=lambda item: item[0])
    return [payload for _, payload in candidates[:limit]]


class Scheduler:
    """Persistent local-time automation with ordered, recorded server operations."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        manager: ProcessManager,
        start: Callable[[Profile], Awaitable[None]],
        data_dir: Path,
        server_root: Path,
        power_helper: Path = POWER_HELPER,
    ) -> None:
        self.factory, self.manager, self.start = factory, manager, start
        self.data_dir, self.server_root = data_dir, server_root
        self.power_helper = power_helper
        self._task: asyncio.Task[None] | None = None

    @property
    def power_capable(self) -> bool:
        return (
            sys.platform.startswith("linux")
            and self.power_helper.is_file()
            and os.access(self.power_helper, os.X_OK)
        )

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
        local_key = now.strftime("%Y-%m-%dT%H:%M")
        with self.factory() as db:
            schedules = db.scalars(select(Schedule).where(Schedule.enabled.is_(True))).all()
            for schedule in schedules:
                profile = db.get(Profile, schedule.profile_id)
                if profile is None or now.weekday() not in parse_weekdays(schedule.weekdays):
                    continue
                if schedule.start_time == clock and schedule.last_start_date != date:
                    schedule.last_start_date = date
                    await self._execute_start(db, profile, "scheduled")
                if schedule.stop_time == clock and schedule.last_stop_date != date:
                    schedule.last_stop_date = date
                    await self._execute_maintenance(
                        db,
                        profile,
                        trigger="scheduled",
                        backup=schedule.backup_before_stop,
                        power_off=schedule.power_off_after_stop,
                        wake_time=schedule.wake_time,
                        wake_weekdays=parse_weekdays(schedule.weekdays),
                        only_when_empty=schedule.only_when_empty,
                        now=now,
                    )

            events = db.scalars(
                select(AutomationEvent).where(
                    AutomationEvent.completed_at.is_(None), AutomationEvent.run_at <= local_key
                )
            ).all()
            for event in events:
                profile = db.get(Profile, event.profile_id)
                event.completed_at = datetime.now(timezone.utc)  # noqa: UP017
                if profile is None:
                    continue
                recurring = db.scalar(
                    select(Schedule).where(Schedule.profile_id == event.profile_id)
                )
                await self._execute_maintenance(
                    db,
                    profile,
                    trigger="one_time",
                    backup=event.backup_before_stop,
                    power_off=event.power_off_after_stop,
                    wake_time=event.wake_time,
                    wake_weekdays=parse_weekdays(recurring.weekdays) if recurring else None,
                    only_when_empty=event.only_when_empty,
                    now=now,
                )
            db.commit()

    async def run_now(
        self, profile_id: str, action: str, *, confirm_power: bool = False
    ) -> AutomationRun:
        with self.factory() as db:
            profile = db.get(Profile, profile_id)
            schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile_id))
            if profile is None:
                raise ValueError("That profile was not found.")
            if action == "start":
                run = await self._execute_start(db, profile, "manual")
            elif schedule is None:
                raise ValueError("Save an automation plan before running it.")
            else:
                if schedule.power_off_after_stop and not confirm_power:
                    raise ValueError("Confirm the host shutdown before running this plan.")
                run = await self._execute_maintenance(
                    db,
                    profile,
                    trigger="manual",
                    backup=schedule.backup_before_stop,
                    power_off=schedule.power_off_after_stop,
                    wake_time=schedule.wake_time,
                    wake_weekdays=parse_weekdays(schedule.weekdays),
                    only_when_empty=schedule.only_when_empty,
                    now=datetime.now().astimezone(),
                )
            db.commit()
            return run

    async def _execute_start(
        self, db: Session, profile: Profile, trigger: str
    ) -> AutomationRun:
        started_at = datetime.now(timezone.utc)  # noqa: UP017
        started = time.monotonic()
        status, detail = "success", f"Started {profile.name}."
        try:
            if self.manager.snapshot()["state"] != "STOPPED":
                status = "skipped"
                detail = "Another server is already running on this host."
            else:
                await self.start(profile)
        except Exception as exc:
            logger.exception("Automation could not start profile %s", profile.id)
            status, detail = "failed", f"The server could not start: {type(exc).__name__}."
        return self._record_run(
            db, profile, trigger, "start", status, ["Start the server"], detail, started_at, started
        )

    async def _execute_maintenance(
        self,
        db: Session,
        profile: Profile,
        *,
        trigger: str,
        backup: bool,
        power_off: bool,
        wake_time: str | None,
        wake_weekdays: list[int] | None,
        only_when_empty: bool,
        now: datetime,
    ) -> AutomationRun:
        started_at = datetime.now(timezone.utc)  # noqa: UP017
        started = time.monotonic()
        steps = automation_steps(backup, power_off)
        status, detail = "success", f"Completed maintenance for {profile.name}."
        snapshot = self.manager.snapshot()
        state = snapshot["state"]
        owner = snapshot.get("profile_id")
        if state not in {"RUNNING", "STARTING", "DEGRADED"}:
            status, detail = "skipped", "The server is already stopped."
        elif owner is not None and owner != profile.id:
            status, detail = "skipped", "Another profile is using the managed server process."
        else:
            try:
                if only_when_empty:
                    online = await self._online_players(profile)
                    if online is None:
                        status = "skipped"
                        detail = "Player status was unavailable, so the server was left running."
                    elif online > 0:
                        status = "skipped"
                        detail = f"Left the server running because {online} player(s) are online."
                if status == "success":
                    await self._maintenance_commands(db, profile, backup, now)
                    graceful = await self.manager.stop(timeout=60.0)
                    if not graceful:
                        raise RuntimeError("the graceful stop timed out")
                    if power_off:
                        await self._power_off(now, wake_time, wake_weekdays)
            except Exception as exc:
                logger.exception("Automation maintenance failed for profile %s", profile.id)
                status = "failed"
                detail = f"Maintenance stopped safely at an error: {exc}"
        return self._record_run(
            db, profile, trigger, "maintenance", status, steps, detail, started_at, started
        )

    async def _maintenance_commands(
        self, db: Session, profile: Profile, backup: bool, now: datetime
    ) -> None:
        await self.manager.command("say Server maintenance is starting now.")
        saving_suspended = False
        try:
            if backup:
                await self.manager.command("save-off")
                saving_suspended = True
            await self.manager.command("save-all flush")
            if backup:
                await self.backup(db, profile, now)
        finally:
            if saving_suspended:
                await self.manager.command("save-on")

    async def backup_before_manual_stop(
        self, db: Session, profile: Profile, now: datetime
    ) -> BackupRecord:
        """Flush and protect a running world before an owner-requested stop."""

        saving_suspended = False
        try:
            await self.manager.command("save-off")
            saving_suspended = True
            await self.manager.command("save-all flush")
            return await self.backup(db, profile, now, trigger="manual")
        finally:
            if saving_suspended:
                await self.manager.command("save-on")

    async def _online_players(self, profile: Profile) -> int | None:
        try:
            server_directory = canonical_child(Path(profile.server_directory), self.server_root)
        except (ValueError, OSError):
            return None
        status = await minecraft_status(read_properties(server_directory))
        online = status.get("online") if status else None
        return online if isinstance(online, int) else None

    async def _power_off(
        self, now: datetime, wake_time: str | None, wake_weekdays: list[int] | None
    ) -> None:
        if not self.power_capable:
            raise RuntimeError("the Linux host power helper is unavailable")
        command = ["sudo", "-n", str(self.power_helper), "poweroff"]
        if wake_time:
            wake_date = (now + timedelta(days=1)).date()
            if wake_weekdays:
                for offset in range(1, 8):
                    candidate = (now + timedelta(days=offset)).date()
                    if candidate.weekday() in wake_weekdays:
                        wake_date = candidate
                        break
            command += ["--wake", f"{wake_date.isoformat()}T{wake_time}:00"]
        process = await asyncio.create_subprocess_exec(*command)
        if await process.wait() != 0:
            raise RuntimeError("the Linux host power helper failed")

    def _record_run(
        self,
        db: Session,
        profile: Profile,
        trigger: str,
        action: str,
        status: str,
        steps: list[str],
        detail: str,
        started_at: datetime,
        started: float,
    ) -> AutomationRun:
        run = AutomationRun(
            profile_id=profile.id,
            trigger=trigger,
            action=action,
            status=status,
            steps=json.dumps(steps),
            detail=detail,
            duration_ms=round((time.monotonic() - started) * 1000),
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),  # noqa: UP017
        )
        db.add(run)
        db.add(
            AuditEvent(
                admin_id=self._admin_id(db),
                category=f"automation_{action}",
                result=status,
                safe_detail=detail,
            )
        )
        db.flush()
        return run

    async def backup(
        self, db: Session, profile: Profile, now: datetime, trigger: str = "schedule"
    ) -> BackupRecord:
        record = BackupRecord(profile_id=profile.id, trigger=trigger, created_at=now)
        db.add(record)
        db.flush()
        # Make progress visible and block a simultaneous manual backup before archive work.
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
                trigger=trigger,
            )
            mirror_note: str | None = None
            if profile.backup_redundancy_enabled:
                try:
                    configured = json.loads(profile.backup_destinations or "[]")
                except (TypeError, json.JSONDecodeError):
                    configured = []
                copied, failed = await asyncio.to_thread(
                    mirror_backup_archive,
                    self.data_dir,
                    profile.id,
                    archive,
                    [Path(value) for value in configured if isinstance(value, str)],
                )
                if failed:
                    mirror_note = (
                        f"The primary backup succeeded, but {len(failed)} approved "
                        "destination(s) were unavailable."
                    )
                elif copied:
                    label = "destination" if len(copied) == 1 else "destinations"
                    mirror_note = f"Mirrored to {len(copied)} approved {label}."
        except BackupError as exc:
            record.status = "failed"
            record.result = str(exc)
            record.completed_at = datetime.now().astimezone()
            record.duration_ms = round((time.monotonic() - started) * 1000)
            db.commit()
            raise

        record.status = "completed"
        record.file_name = archive.file_name
        record.manifest_name = archive.manifest_name
        record.sha256 = archive.sha256
        record.included_paths = json.dumps(list(archive.included_paths))
        record.size_bytes = archive.size_bytes
        record.duration_ms = round((time.monotonic() - started) * 1000)
        record.result = " ".join(
            part
            for part in (
                f"Protected {', '.join(archive.included_paths)}.",
                mirror_note,
            )
            if part
        )
        record.completed_at = datetime.now().astimezone()
        enforce_retention(db, profile, self.data_dir)
        db.commit()
        return record

    @staticmethod
    def _admin_id(db: Session) -> str:
        return db.scalars(select(Administrator.id)).first() or "system"
