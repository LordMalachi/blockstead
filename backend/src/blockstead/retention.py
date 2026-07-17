"""Apply a profile's backup retention policy to its completed archives."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .backups import RetentionEntry, backup_directory, select_expired
from .models import BackupRecord, Profile

logger = logging.getLogger(__name__)


def enforce_retention(
    db: Session, profile: Profile, destination_root: Path, now: datetime | None = None
) -> list[str]:
    """Remove archives the policy no longer keeps; returns expired backup ids.

    Only completed backups whose archive files still exist count toward the
    policy, and the newest of them is never removed. Records stay in history
    with status ``expired`` so the owner can see what happened. The caller is
    responsible for committing the session.
    """

    if (
        profile.backup_keep_count is None
        and profile.backup_keep_days is None
        and profile.backup_max_total_mb is None
    ):
        return []

    now = now or datetime.now(timezone.utc)  # noqa: UP017
    records = db.scalars(
        select(BackupRecord).where(
            BackupRecord.profile_id == profile.id,
            BackupRecord.status == "completed",
        )
    ).all()
    directory = backup_directory(destination_root, profile.id)
    on_disk: dict[str, BackupRecord] = {}
    entries: list[RetentionEntry] = []
    for record in records:
        if not record.file_name or not (directory / record.file_name).is_file():
            continue
        created = record.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)  # noqa: UP017
        on_disk[record.id] = record
        entries.append(
            RetentionEntry(
                backup_id=record.id,
                created_at=created,
                size_bytes=record.size_bytes or 0,
            )
        )

    expired_ids = select_expired(
        entries,
        now,
        profile.backup_keep_count,
        profile.backup_keep_days,
        profile.backup_max_total_mb,
    )
    removed: list[str] = []
    for backup_id in expired_ids:
        record = on_disk[backup_id]
        try:
            if record.file_name:
                (directory / record.file_name).unlink(missing_ok=True)
            if record.manifest_name:
                (directory / record.manifest_name).unlink(missing_ok=True)
        except OSError:
            # Leave the record alone; a file we could not delete is still there.
            logger.exception("Could not remove expired backup %s", backup_id)
            continue
        record.status = "expired"
        record.result = f"{record.result} Removed by the retention policy."
        db.add(record)
        removed.append(backup_id)
    return removed
