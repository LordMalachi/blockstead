"""Collect what a support conversation needs into one shareable report.

The application keeps its most recent log records in a small in-memory ring
buffer and mirrors them to a rotating file under the data directory. A
diagnostic report bundles those records with the software settings, host
health, and recent operation history so an owner can download a single file
and send it along when asking for help. Everything in the report is redacted
so it never exposes the owner's Linux account name, and nothing leaves the
computer unless the owner shares the file themselves.
"""

import logging
import platform
import re
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import __version__
from .config import Settings
from .java_runtime import discover_java_runtimes
from .models import AuditEvent, AutomationRun, BackupRecord, Profile, Schedule

REPORT_VERSION = 1
BUFFER_LIMIT = 400
ERROR_TAIL_LIMIT = 50
LOG_TAIL_LIMIT = 200
LOG_FILE_BYTES = 1_000_000
LOG_FILE_BACKUPS = 3

BUFFER_HANDLER_NAME = "blockstead-diagnostics-buffer"
FILE_HANDLER_NAME = "blockstead-diagnostics-file"

_FILE_FORMAT = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
_HOME_PATTERN = re.compile(r"(/home/|/Users/)[^/\s'\"]+")

log = logging.getLogger(__name__)


def redact(text: str) -> str:
    """Hide the account name inside home-directory paths before it leaves the app."""
    return _HOME_PATTERN.sub(r"\1[account]", text)


@dataclass(frozen=True)
class BufferedRecord:
    at: str
    levelno: int
    level: str
    logger: str
    message: str

    def payload(self) -> dict[str, object]:
        return {"at": self.at, "level": self.level, "logger": self.logger, "message": self.message}


class DiagnosticLogBuffer(logging.Handler):
    """Keep the most recent application log records in memory for diagnostic reports."""

    def __init__(self, limit: int = BUFFER_LIMIT) -> None:
        super().__init__(level=logging.INFO)
        self.entries: deque[BufferedRecord] = deque(maxlen=limit)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info and record.exc_info != (None, None, None):
                message = f"{message}\n{_FILE_FORMAT.formatException(record.exc_info)}"
        except Exception:  # noqa: BLE001 - a broken record must never break logging
            message = str(record.msg)
        self.entries.append(
            BufferedRecord(
                at=datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),  # noqa: UP017
                levelno=record.levelno,
                level=record.levelname,
                logger=record.name,
                message=redact(message),
            )
        )

    def tail(self, limit: int, minimum_level: int = logging.INFO) -> list[dict[str, object]]:
        selected = [entry for entry in self.entries if entry.levelno >= minimum_level]
        return [entry.payload() for entry in selected[-limit:]]

    def window(self, center: datetime, minutes: int = 15) -> list[dict[str, object]]:
        """Return buffered records near one activity event for focused support."""
        if center.tzinfo is None:
            center = center.replace(tzinfo=timezone.utc)  # noqa: UP017
        start, end = center - timedelta(minutes=minutes), center + timedelta(minutes=minutes)
        return [
            entry.payload()
            for entry in self.entries
            if start <= datetime.fromisoformat(entry.at) <= end
        ]


def attach_logging(data_dir: Path) -> DiagnosticLogBuffer:
    """Route application logs into a ring buffer and a rotating file under data_dir.

    Handlers hang off the shared "blockstead" logger, so a fresh application
    instance (each test builds one) must replace the previous instance's
    handlers rather than stack alongside them.
    """
    logger = logging.getLogger("blockstead")
    logger.setLevel(logging.INFO)
    # A logging.config.fileConfig call elsewhere (alembic's default) may have
    # disabled this logger wholesale; diagnostics must survive that.
    logger.disabled = False
    for handler in list(logger.handlers):
        if handler.get_name() in {BUFFER_HANDLER_NAME, FILE_HANDLER_NAME}:
            logger.removeHandler(handler)
            handler.close()
    buffer = DiagnosticLogBuffer()
    buffer.set_name(BUFFER_HANDLER_NAME)
    logger.addHandler(buffer)
    try:
        log_dir = data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        file_handler = RotatingFileHandler(
            log_dir / "blockstead.log",
            maxBytes=LOG_FILE_BYTES,
            backupCount=LOG_FILE_BACKUPS,
            encoding="utf-8",
        )
        file_handler.setFormatter(_FILE_FORMAT)
        file_handler.setLevel(logging.INFO)
        file_handler.set_name(FILE_HANDLER_NAME)
        logger.addHandler(file_handler)
    except OSError:
        log.warning("Could not open the application log file; keeping recent logs in memory only")
    return buffer


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc).isoformat()  # noqa: UP017


def build_report(
    *,
    config: Settings,
    buffer: DiagnosticLogBuffer,
    server: dict[str, object],
    static_dir: Path | None,
    db: Session,
    focus_event: AuditEvent | None = None,
) -> dict[str, object]:
    """Assemble the diagnostic report an owner downloads to ask for help."""
    now = datetime.now(timezone.utc)  # noqa: UP017
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(config.data_dir))
    profiles = db.scalars(select(Profile).order_by(Profile.created_at)).all()
    schedules = db.scalars(select(Schedule)).all()
    runs = db.scalars(
        select(AutomationRun).order_by(AutomationRun.started_at.desc()).limit(10)
    ).all()
    backups = db.scalars(
        select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(10)
    ).all()
    audit = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(20)).all()
    report: dict[str, object] = {
        "report_version": REPORT_VERSION,
        "generated_at": now.isoformat(),
        "application": {
            "version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "settings": {
            "bind_host": config.bind_host,
            "port": config.port,
            "data_dir": redact(str(config.data_dir)),
            "server_root": redact(str(config.server_root)),
            "secure_cookies": config.secure_cookies,
            "session_hours": config.session_hours,
            "allowed_origins": sorted(config.origins),
            "static_dir_present": static_dir is not None,
        },
        "host": {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory": {
                "total_bytes": memory.total,
                "used_bytes": memory.used,
                "percent": memory.percent,
            },
            "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "percent": disk.percent},
            "uptime_seconds": max(0.0, now.timestamp() - psutil.boot_time()),
        },
        "java_runtimes": [
            {"path": redact(runtime.path), "version": runtime.version, "major": runtime.major}
            for runtime in discover_java_runtimes()
        ],
        "server": server,
        "profiles": [
            {
                "id": profile.id,
                "name": profile.name,
                "distribution": profile.distribution,
                "minecraft_version": profile.minecraft_version,
                "loader_version": profile.loader_version,
                "is_fixture": profile.is_fixture,
                "directory": redact(profile.server_directory),
            }
            for profile in profiles
        ],
        "schedules": [
            {
                "profile_id": schedule.profile_id,
                "enabled": schedule.enabled,
                "start_time": schedule.start_time,
                "stop_time": schedule.stop_time,
                "weekdays": schedule.weekdays,
            }
            for schedule in schedules
        ],
        "recent_automation_runs": [
            {
                "trigger": run.trigger,
                "action": run.action,
                "status": run.status,
                "detail": redact(run.detail),
                "started_at": _timestamp(run.started_at),
            }
            for run in runs
        ],
        "recent_backups": [
            {
                "status": record.status,
                "trigger": record.trigger,
                "size_bytes": record.size_bytes,
                "duration_ms": record.duration_ms,
                "result": redact(record.result),
                "created_at": _timestamp(record.created_at),
            }
            for record in backups
        ],
        "audit_tail": [
            {
                "category": event.category,
                "result": event.result,
                "detail": redact(event.safe_detail),
                "created_at": _timestamp(event.created_at),
            }
            for event in audit
        ],
        "recent_errors": buffer.tail(ERROR_TAIL_LIMIT, logging.WARNING),
        "recent_log": buffer.tail(LOG_TAIL_LIMIT, logging.INFO),
    }
    if focus_event is not None:
        report["focus_event"] = {
            "id": focus_event.id,
            "profile_id": focus_event.profile_id,
            "category": focus_event.category,
            "result": focus_event.result,
            "detail": redact(focus_event.safe_detail),
            "created_at": _timestamp(focus_event.created_at),
        }
        report["focus_log_window"] = buffer.window(focus_event.created_at)
    return report
