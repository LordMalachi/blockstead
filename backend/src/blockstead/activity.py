"""Human-readable activity and local notification helpers."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Administrator, AuditEvent, NotificationPreference, Profile

CATEGORY_GROUPS: dict[str, str] = {
    "profile_import": "lifecycle",
    "profile_provision": "lifecycle",
    "modpack_install": "lifecycle",
    "eula_accept": "lifecycle",
    "server_start": "lifecycle",
    "server_stop": "lifecycle",
    "server_restart": "lifecycle",
    "server_crash": "lifecycle",
    "manual_backup": "backup",
    "backup_restore": "backup",
    "backup_policy": "backup",
    "settings_update": "settings",
    "settings_raw_update": "settings",
    "settings_change": "settings",
    "extension_install": "extension",
    "extension_toggle": "extension",
    "extension_update": "extension",
    "extension_remove": "extension",
    "extension_upload": "extension",
    "mod_config_update": "extension",
    "player_action": "player",
    "console_command": "player",
    "guided_command": "player",
    "schedule_update": "automation",
    "automation_event": "automation",
    "automation_start": "automation",
    "automation_maintenance": "automation",
    "update_install": "update",
}

CATEGORY_TITLES: dict[str, str] = {
    "profile_import": "Server imported",
    "profile_provision": "Server created",
    "modpack_install": "Modpack installed",
    "eula_accept": "Minecraft EULA accepted",
    "server_start": "Server start requested",
    "server_stop": "Server stop requested",
    "server_restart": "Server restart requested",
    "server_crash": "Server crashed",
    "manual_backup": "Manual backup",
    "backup_restore": "Backup restore",
    "backup_policy": "Backup protection updated",
    "settings_update": "Server settings updated",
    "settings_raw_update": "Advanced settings updated",
    "settings_change": "Workspace settings updated",
    "extension_install": "Extension installed",
    "extension_toggle": "Extension state changed",
    "extension_update": "Extension updated",
    "extension_remove": "Extension removed",
    "extension_upload": "Extension uploaded",
    "mod_config_update": "Mod configuration updated",
    "player_action": "Player access changed",
    "console_command": "Console command sent",
    "guided_command": "Guided command sent",
    "schedule_update": "Schedule updated",
    "automation_event": "One-time maintenance changed",
    "automation_start": "Automated start",
    "automation_maintenance": "Automated maintenance",
    "update_install": "Blockstead updated",
}


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc).isoformat()  # noqa: UP017


def recovery_path(category: str, profile_id: str | None) -> str:
    if not profile_id:
        return "/system" if CATEGORY_GROUPS.get(category) in {"settings", "update"} else "/servers"
    section = {
        "backup": "backups",
        "extension": "mods",
        "player": "players",
        "settings": "settings",
        "automation": "schedule",
        "lifecycle": "console",
    }.get(CATEGORY_GROUPS.get(category, ""), "overview")
    return f"/servers/{profile_id}/{section}"


def event_payload(
    event: AuditEvent,
    *,
    actor: Administrator | None = None,
    profile: Profile | None = None,
) -> dict[str, Any]:
    group = CATEGORY_GROUPS.get(event.category, "system")
    failed = event.result in {"failed", "error", "crashed"}
    return {
        "id": event.id,
        "category": event.category,
        "group": group,
        "title": CATEGORY_TITLES.get(event.category, event.category.replace("_", " ").title()),
        "result": event.result,
        "severity": "danger" if failed else "success",
        "detail": event.safe_detail,
        "actor": actor.username if actor else "Blockstead",
        "profile": {"id": profile.id, "name": profile.name} if profile else None,
        "created_at": utc_timestamp(event.created_at),
        "recovery_to": recovery_path(event.category, event.profile_id),
        "report_url": f"/api/v1/activity/{event.id}/report",
    }


def list_activity(
    db: Session,
    *,
    profile_id: str | None,
    group: str | None,
    result: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    rows = db.execute(
        select(AuditEvent, Administrator, Profile)
        .join(Administrator, Administrator.id == AuditEvent.admin_id)
        .outerjoin(Profile, Profile.id == AuditEvent.profile_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(500)
    ).all()
    selected = [
        event_payload(event, actor=actor, profile=profile)
        for event, actor, profile in rows
        if (profile_id is None or event.profile_id == profile_id)
        and (group is None or CATEGORY_GROUPS.get(event.category, "system") == group)
        and (result is None or event.result == result)
    ]
    return {
        "events": selected[offset : offset + limit],
        "total": len(selected),
        "limit": limit,
        "offset": offset,
    }


def preferences_for(
    db: Session, admin_id: str, *, persist: bool = True
) -> NotificationPreference:
    row = db.get(NotificationPreference, admin_id)
    if row is None:
        row = NotificationPreference(
            admin_id=admin_id,
            server_crashes=True,
            failed_backups=True,
            low_disk_space=True,
            completed_updates=True,
        )
        if persist:
            db.add(row)
            db.flush()
    return row


def preferences_payload(row: NotificationPreference) -> dict[str, Any]:
    return {
        "server_crashes": row.server_crashes,
        "failed_backups": row.failed_backups,
        "low_disk_space": row.low_disk_space,
        "completed_updates": row.completed_updates,
        "last_seen_at": utc_timestamp(row.last_seen_at) if row.last_seen_at else None,
    }
