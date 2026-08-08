"""Human-readable activity and local notification helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Administrator, AuditEvent, NotificationPreference, Profile

CATEGORY_GROUPS: dict[str, str] = {
    "profile_import": "lifecycle",
    "profile_provision": "lifecycle",
    "profile_remove": "lifecycle",
    "modpack_install": "lifecycle",
    "loader_migration": "lifecycle",
    "server_upgrade": "lifecycle",
    "profile_version": "lifecycle",
    "eula_accept": "lifecycle",
    "server_start": "lifecycle",
    "server_stop": "lifecycle",
    "server_restart": "lifecycle",
    "server_crash": "lifecycle",
    "manual_backup": "backup",
    "backup_restore": "backup",
    "backup_recovery_drill": "backup",
    "backup_destination_check": "backup",
    "world_cleanup": "backup",
    "diagnostic_capture": "system",
    "backup_policy": "backup",
    "settings_update": "settings",
    "settings_raw_update": "settings",
    "settings_change": "settings",
    "extension_install": "extension",
    "extension_toggle": "extension",
    "extension_update": "extension",
    "extension_remove": "extension",
    "extension_upload": "extension",
    "shared_map_profile": "extension",
    "loadout_validation": "extension",
    "mod_config_update": "extension",
    "player_action": "player",
    "console_command": "player",
    "guided_command": "player",
    "troubleshooting_repair": "system",
    "connection_repair": "system",
    "maintenance_preflight": "maintenance",
    "maintenance_schedule": "maintenance",
    "file_download": "files",
    "file_upload": "files",
    "file_edit": "files",
    "file_rename": "files",
    "file_delete": "files",
    "file_archive_extract": "files",
    "schedule_update": "automation",
    "automation_event": "automation",
    "automation_start": "automation",
    "automation_maintenance": "automation",
    "update_install": "update",
}

CATEGORY_TITLES: dict[str, str] = {
    "profile_import": "Server imported",
    "profile_provision": "Server created",
    "profile_remove": "Server removed",
    "modpack_install": "Modpack installed",
    "loader_migration": "Modded server copy created",
    "server_upgrade": "Server upgraded",
    "profile_version": "Minecraft version recorded",
    "eula_accept": "Minecraft EULA accepted",
    "server_start": "Server start requested",
    "server_stop": "Server stop requested",
    "server_restart": "Server restart requested",
    "server_crash": "Server crashed",
    "manual_backup": "Manual backup",
    "backup_restore": "Backup restore",
    "backup_recovery_drill": "Recovery drill",
    "backup_destination_check": "Backup destination resilience check",
    "world_cleanup": "Reviewed world-care cleanup",
    "diagnostic_capture": "Local diagnostic capture",
    "backup_policy": "Backup protection updated",
    "settings_update": "Server settings updated",
    "settings_raw_update": "Advanced settings updated",
    "settings_change": "Workspace settings updated",
    "extension_install": "Extension installed",
    "extension_toggle": "Extension state changed",
    "extension_update": "Extension updated",
    "extension_remove": "Extension removed",
    "extension_upload": "Extension uploaded",
    "shared_map_profile": "squaremap low-resource profile applied",
    "loadout_validation": "Loadout tested privately",
    "mod_config_update": "Mod configuration updated",
    "player_action": "Player access changed",
    "console_command": "Console command sent",
    "guided_command": "Guided command sent",
    "troubleshooting_repair": "Troubleshooting repair requested",
    "connection_repair": "Connection repair applied",
    "maintenance_preflight": "Maintenance change reviewed",
    "maintenance_schedule": "Maintenance window scheduled",
    "file_download": "File downloaded",
    "file_upload": "File uploaded",
    "file_edit": "File edited",
    "file_rename": "File renamed",
    "file_delete": "File deleted",
    "file_archive_extract": "Archive extracted",
    "schedule_update": "Schedule updated",
    "automation_event": "One-time maintenance changed",
    "automation_start": "Automated start",
    "automation_maintenance": "Automated maintenance",
    "update_install": "Blockstead updated",
}

INCIDENT_GROUPS = {
    "lifecycle",
    "backup",
    "settings",
    "extension",
    "automation",
    "maintenance",
    "system",
}
INCIDENT_CATEGORIES = {
    category for category, group in CATEGORY_GROUPS.items() if group in INCIDENT_GROUPS
}
INCIDENT_WINDOW_MINUTES = 15
INCIDENT_FACT_LIMIT = 50


def utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
    return value.astimezone(timezone.utc).isoformat()  # noqa: UP017


def recovery_path(category: str, profile_id: str | None) -> str:
    if category == "troubleshooting_repair":
        return "/help#server-troubleshooter"
    if not profile_id:
        return "/system" if CATEGORY_GROUPS.get(category) in {"settings", "update"} else "/servers"
    section = {
        "backup": "backups",
        "extension": "mods",
        "player": "players",
        "settings": "settings",
        "automation": "schedule",
        "lifecycle": "console",
        "files": "files",
        "maintenance": "maintenance",
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
    skipped = event.result in {"skipped", "partial", "warning", "refused", "forced"}
    return {
        "id": event.id,
        "category": event.category,
        "group": group,
        "title": CATEGORY_TITLES.get(event.category, event.category.replace("_", " ").title()),
        "result": event.result,
        "severity": "danger" if failed else "warning" if skipped else "success",
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


def incident_payload(
    db: Session,
    *,
    anchor: AuditEvent,
    log_entries: list[dict[str, object]],
) -> dict[str, Any]:
    """Build a bounded incident story without treating nearby timing as causation."""

    anchor_at = anchor.created_at
    if anchor_at.tzinfo is None:
        anchor_at = anchor_at.replace(tzinfo=timezone.utc)  # noqa: UP017
    start = anchor_at - timedelta(minutes=INCIDENT_WINDOW_MINUTES)
    end = anchor_at + timedelta(minutes=INCIDENT_WINDOW_MINUTES)
    profile_filter = (
        AuditEvent.profile_id.is_(None)
        if anchor.profile_id is None
        else AuditEvent.profile_id == anchor.profile_id
    )
    rows = db.execute(
        select(AuditEvent, Administrator, Profile)
        .join(Administrator, Administrator.id == AuditEvent.admin_id)
        .outerjoin(Profile, Profile.id == AuditEvent.profile_id)
        .where(
            profile_filter,
            AuditEvent.created_at >= start,
            AuditEvent.created_at <= end,
            AuditEvent.category.in_(INCIDENT_CATEGORIES),
            AuditEvent.id != anchor.id,
        )
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        .limit(INCIDENT_FACT_LIMIT)
    ).all()
    facts = [
        event_payload(event, actor=actor, profile=profile)
        for event, actor, profile in rows
    ]

    anchor_actor = db.get(Administrator, anchor.admin_id)
    anchor_profile = db.get(Profile, anchor.profile_id) if anchor.profile_id else None
    anchor_value = event_payload(anchor, actor=anchor_actor, profile=anchor_profile)
    scope_label = "same-server" if anchor.profile_id else "workspace"
    if facts:
        timing_detail = (
            f"{len(facts)} other {scope_label} event(s) were recorded within 15 minutes before "
            "or after this event. Their order and timing are recorded facts; proximity does "
            "not establish that one caused another."
        )
    else:
        timing_detail = (
            f"No other {scope_label} lifecycle, backup, settings, extension, automation, "
            "maintenance, or system event was recorded within 15 minutes."
        )

    safe_logs = [
        {
            "at": str(entry.get("at") or ""),
            "level": str(entry.get("level") or "UNKNOWN"),
            "logger": str(entry.get("logger") or "blockstead"),
            "message": str(entry.get("message") or ""),
        }
        for entry in log_entries
    ]
    log_context = {
        "state": "available" if safe_logs else "unavailable",
        "detail": (
            "These redacted buffered log entries were recorded within 15 minutes of the "
            "anchor event; they are context, not a confirmed cause."
            if safe_logs
            else (
                "No redacted buffered log entries remain for this time window. The focused "
                "report still preserves the durable event record."
            )
        ),
        "entries": safe_logs,
    }

    failed = anchor.result in {"failed", "error", "crashed", "forced", "refused"}
    destination = recovery_path(anchor.category, anchor.profile_id)
    return {
        "anchor": anchor_value,
        "recorded_facts": facts,
        "observed_timing": {
            "label": "Recorded events around this moment",
            "detail": timing_detail,
        },
        "possible_explanation": {
            "state": "unconfirmed",
            "detail": (
                "Blockstead has not confirmed what caused this event. Nearby events and log "
                "entries may help an owner investigate, but are not proof of causation."
            ),
        },
        "log_context": log_context,
        "safe_next_action": {
            "label": "Open recovery" if failed else "Review the relevant workspace",
            "detail": (
                "Review the recorded event and focused support report before restarting or "
                "changing server files and settings."
                if failed
                else "Review the detailed workspace before making another change."
            ),
            "to": destination,
        },
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
            failed_automations=True,
            low_disk_space=True,
            completed_updates=True,
            show_player_avatars=False,
        )
        if persist:
            db.add(row)
            db.flush()
    return row


def preferences_payload(row: NotificationPreference) -> dict[str, Any]:
    return {
        "server_crashes": row.server_crashes,
        "failed_backups": row.failed_backups,
        "failed_automations": row.failed_automations,
        "low_disk_space": row.low_disk_space,
        "completed_updates": row.completed_updates,
        "show_player_avatars": row.show_player_avatars,
        "last_seen_at": utc_timestamp(row.last_seen_at) if row.last_seen_at else None,
    }
