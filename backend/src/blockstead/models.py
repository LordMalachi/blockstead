from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)  # noqa: UP017


class Administrator(Base):
    __tablename__ = "administrators"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default="owner")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordRecoveryToken(Base):
    __tablename__ = "password_recovery_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class SavedSetup(Base):
    __tablename__ = "saved_setups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(80))
    created_by_admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedSetupVariant(Base):
    __tablename__ = "saved_setup_variants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    setup_id: Mapped[str] = mapped_column(ForeignKey("saved_setups.id", ondelete="CASCADE"))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True
    )
    source_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    protection_backup_id: Mapped[str | None] = mapped_column(
        ForeignKey("backups.id", ondelete="SET NULL"), nullable=True
    )
    copied_paths: Mapped[str] = mapped_column(Text, default="[]")
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
    failed_automations: Mapped[bool] = mapped_column(Boolean, default=True)
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


class PerformanceSample(Base):
    """A labelled Paper performance response collected by bounded console commands."""

    __tablename__ = "performance_samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(120))
    sampling_period_seconds: Mapped[int] = mapped_column(Integer)
    tps_one_minute: Mapped[float | None] = mapped_column(Float, nullable=True)
    tps_five_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    tps_fifteen_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    mspt_five_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    mspt_ten_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    mspt_sixty_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class DiagnosticCapture(Base):
    """An owner-requested local performance capture and its private transcript."""

    __tablename__ = "diagnostic_captures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    duration_seconds: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="in_progress")
    output_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupDestinationCheck(Base):
    """Latest read/write evidence for one owner-approved backup destination."""

    __tablename__ = "backup_destination_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    destination_path: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(24))
    write_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    read_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    detail: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
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


class NotificationIntegration(Base):
    __tablename__ = "notification_integrations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32), default="discord_webhook")
    secret_key: Mapped[str] = mapped_column(String(64), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    integration_id: Mapped[str] = mapped_column(
        ForeignKey("notification_integrations.id", ondelete="CASCADE"), index=True
    )
    alert_id: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="Delivery is queued.")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscordPairing(Base):
    """Short-lived owner-created claim waiting for a Discord confirmation."""

    __tablename__ = "discord_pairings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    relay_pairing_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_application_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_guild_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    claimed_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscordConnection(Base):
    """A confirmed one-profile to one-Discord-channel status connection."""

    __tablename__ = "discord_connections"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "guild_id", "channel_id", name="uq_discord_connection_channel"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    admin_id: Mapped[str] = mapped_column(ForeignKey("administrators.id", ondelete="CASCADE"))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), unique=True
    )
    relay_connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    application_id: Mapped[str] = mapped_column(String(32))
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    owner_user_id: Mapped[str] = mapped_column(String(32))
    authorized_user_ids: Mapped[str] = mapped_column(Text, default="[]")
    authorized_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    share_address: Mapped[bool] = mapped_column(Boolean, default=False)
    publish_address: Mapped[bool] = mapped_column(Boolean, default=False)
    status_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_relay_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_result: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_status_payload: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscordCommandAudit(Base):
    """Safe audit metadata for a Discord command, never the full message payload."""

    __tablename__ = "discord_command_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    connection_id: Mapped[str | None] = mapped_column(
        ForeignKey("discord_connections.id", ondelete="SET NULL"), nullable=True
    )
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True
    )
    guild_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    command: Mapped[str] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(24))
    safe_detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
