from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


class Administrator(Base):
    __tablename__ = "administrators"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Profile(Base):
    __tablename__ = "profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80))
    server_directory: Mapped[str] = mapped_column(Text, unique=True)
    distribution: Mapped[str] = mapped_column(String(24))
    minecraft_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    loader_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    # Backup retention policy. NULL means "no limit" for that rule; the newest
    # completed backup always survives every rule.
    backup_keep_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=10)
    backup_keep_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    backup_max_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    backup_redundancy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_destinations: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id"))
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(24))
    safe_detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationPreference(Base):
    """Per-owner local alert choices and the activity inbox read marker."""

    __tablename__ = "notification_preferences"
    admin_id: Mapped[str] = mapped_column(
        ForeignKey("administrators.id", ondelete="CASCADE"), primary_key=True
    )
    server_crashes: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_backups: Mapped[bool] = mapped_column(Boolean, default=True)
    low_disk_space: Mapped[bool] = mapped_column(Boolean, default=True)
    completed_updates: Mapped[bool] = mapped_column(Boolean, default=True)
    # Off by default: turning this on has the browser fetch skin images from a
    # third-party service (keyed by player UUID), which Blockstead otherwise
    # never contacts on the owner's behalf.
    show_player_avatars: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    stop_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    backup_before_stop: Mapped[bool] = mapped_column(Boolean, default=True)
    power_off_after_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    wake_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    weekdays: Mapped[str] = mapped_column(String(32), default="0,1,2,3,4,5,6")
    only_when_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    last_start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    last_stop_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AutomationEvent(Base):
    __tablename__ = "automation_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    run_at: Mapped[str] = mapped_column(String(16), index=True)
    backup_before_stop: Mapped[bool] = mapped_column(Boolean, default=True)
    power_off_after_stop: Mapped[bool] = mapped_column(Boolean, default=False)
    wake_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    only_when_empty: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AutomationRun(Base):
    __tablename__ = "automation_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    steps: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupRecord(Base):
    __tablename__ = "backups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    method: Mapped[str] = mapped_column(String(24), default="world_archive")
    trigger: Mapped[str] = mapped_column(String(24), default="manual")
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    included_paths: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="Backup is in progress.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlayerSession(Base):
    """A best-effort join/leave interval parsed from the managed server's log.

    Only recognized log phrasing (currently vanilla's own English messages)
    produces a row; an unrecognized format simply means no session history
    exists for that profile, never a guessed one.
    """

    __tablename__ = "player_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    player_name: Mapped[str] = mapped_column(String(16), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricSample(Base):
    __tablename__ = "metric_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    disk_percent: Mapped[float] = mapped_column(Float)
    process_memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    world_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class AppSecret(Base):
    """Small owner-provided secrets (external API keys), never exported."""

    __tablename__ = "app_secrets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
