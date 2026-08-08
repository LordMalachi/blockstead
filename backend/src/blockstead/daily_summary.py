"""Pure, evidence-labelled read model for calm daily server operations."""

from collections.abc import Mapping, Sequence
from typing import Any

_WARNING_PRIORITY = {
    "server-state": 0,
    "disk-space": 1,
    "backup-missing": 2,
    "backup-unverified": 3,
    "eula": 4,
    "java-runtime": 5,
    "launch-files": 6,
    "performance-evidence": 7,
    "local-status": 8,
    "local-bind": 9,
    "public-address-unavailable": 10,
}


def _verified_backup(backup: Mapping[str, object] | None) -> bool:
    """Only call an available completed archive with a recorded checksum verified."""

    if backup is None:
        return False
    checksum = backup.get("sha256")
    return bool(
        backup.get("status") == "completed"
        and backup.get("archive_available") is True
        and isinstance(checksum, str)
        and len(checksum) == 64
        and all(character in "0123456789abcdef" for character in checksum.casefold())
    )


def _daily_focus(
    *,
    profile_id: str,
    state: str,
    warnings: Sequence[Mapping[str, str]],
    backup_verified: bool,
    backup_present: bool,
) -> dict[str, str]:
    candidates: list[Mapping[str, str]] = list(warnings)
    if backup_present and not backup_verified:
        candidates.append(
            {
                "code": "backup-unverified",
                "title": "Backup evidence needs review",
                "detail": (
                    "The latest completed backup does not have both a recorded checksum and "
                    "an available local archive, so it is not shown as verified."
                ),
                "to": f"/servers/{profile_id}/backups",
                "severity": "warning",
            }
        )
    if candidates:
        severity_rank = {"danger": 0, "warning": 1, "success": 2}
        selected = min(
            enumerate(candidates),
            key=lambda item: (
                severity_rank.get(str(item[1].get("severity")), 1),
                _WARNING_PRIORITY.get(str(item[1].get("code")), 100),
                item[0],
            ),
        )[1]
        code = str(selected.get("code") or "current-warning")
        severity = str(selected.get("severity") or "warning")
        if severity not in {"success", "warning", "danger"}:
            severity = "warning"
        return {
            "kind": "warning",
            "title": str(selected.get("title") or "Server needs attention"),
            "detail": str(selected.get("detail") or "Review the current server evidence."),
            "to": str(selected.get("to") or f"/servers/{profile_id}/overview"),
            "severity": severity,
            "evidence": (
                f"Selected from the current {code} evidence. This warning does not assert "
                "an unconfirmed cause."
            ),
        }

    if state == "STOPPED":
        return {
            "kind": "action",
            "title": "Start the server when you are ready",
            "detail": "Open the console to review readiness and start this server.",
            "to": f"/servers/{profile_id}/console",
            "severity": "success",
            "evidence": "Blockstead currently observes the managed process as stopped.",
        }
    return {
        "kind": "clear",
        "title": "No urgent action is recorded",
        "detail": "Keep an eye on the next operation and recent Activity.",
        "to": "/activity",
        "severity": "success",
        "evidence": "No current overview warning outranked this routine review action.",
    }


def build_daily_summary(
    *,
    profile: Mapping[str, str],
    state: Mapping[str, object],
    join: Mapping[str, object],
    players: Mapping[str, object],
    backup: Mapping[str, object] | None,
    next_operation: Mapping[str, object] | None,
    warnings: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Return one concise summary without converting observations into causation claims."""

    profile_id = profile["id"]
    profile_name = profile["name"]
    state_value = str(state.get("value") or "UNKNOWN")
    player_status_available = players.get("available") is True
    player_status_responded = players.get("status_outcome") == "responded"

    if state_value == "RUNNING" and player_status_available and player_status_responded:
        playable = {
            "state": "locally_responding",
            "label": "Minecraft is responding locally",
            "detail": (
                "Minecraft answered Blockstead's bounded local server-list status check."
            ),
            "evidence": (
                "Observed from a current local Minecraft status response; this does not prove "
                "that remote players can connect."
            ),
        }
    elif state_value == "RUNNING":
        playable = {
            "state": "running_unconfirmed",
            "label": "The process is running",
            "detail": "Blockstead has not confirmed current Minecraft join availability.",
            "evidence": (
                "Observed from the managed process state. A RUNNING process alone does not "
                "prove that players can connect."
            ),
        }
    elif state_value in {"STARTING", "STOPPING"}:
        playable = {
            "state": "transitioning",
            "label": f"The server is {state_value.lower()}",
            "detail": "Join availability is not claimed while the process changes state.",
            "evidence": "Observed from the current managed process transition.",
        }
    elif state_value in {"CRASHED", "DEGRADED"}:
        playable = {
            "state": "needs_attention",
            "label": "The server needs attention",
            "detail": str(state.get("reason") or "Review the current server state."),
            "evidence": (
                "Observed from the managed process state; the state does not by itself prove a "
                "root cause."
            ),
        }
    else:
        playable = {
            "state": "stopped",
            "label": "The server is stopped",
            "detail": f"{profile_name} is not currently accepting joins.",
            "evidence": "Observed from the current managed process state.",
        }

    address = join.get("address")
    local_only = join.get("local_only") is True
    join_summary: dict[str, object]
    if isinstance(address, str):
        join_summary = {
            "address": address,
            "label": "This-computer join address" if local_only else "Local join address",
            "detail": (
                "This address is restricted to the Blockstead computer."
                if local_only
                else "Use this address from the local network; outside reachability is not proven."
            ),
            "evidence": (
                "Derived from server.properties and detected local interfaces, not from an "
                "outside-network connection test."
            ),
        }
    else:
        join_summary = {
            "address": None,
            "label": "No local join address detected",
            "detail": "Open connection help before sharing an address.",
            "evidence": "No usable local interface address was observed for the configured bind.",
        }

    online = players.get("online") if player_status_available else None
    maximum = players.get("max")
    maximum_value = maximum if isinstance(maximum, int) else 0
    if isinstance(online, int):
        player_summary = {
            "online": online,
            "max": maximum_value,
            "label": f"{online} of {maximum_value} players online",
            "detail": "Minecraft returned the current player count and capacity.",
            "evidence": "Observed from the current local Minecraft status response.",
        }
    else:
        player_summary = {
            "online": None,
            "max": maximum_value,
            "label": f"Up to {maximum_value} players configured",
            "detail": "The current online-player count is unavailable.",
            "evidence": (
                "Capacity is recorded in server.properties; no current player count is claimed."
            ),
        }

    backup_verified = _verified_backup(backup)
    backup_to = f"/servers/{profile_id}/backups"
    if backup_verified and backup is not None:
        backup_summary = {
            "state": "verified",
            "label": "Verified backup available",
            "detail": str(backup.get("result") or "A protected world archive is available."),
            "created_at": (
                str(backup["created_at"]) if backup.get("created_at") is not None else None
            ),
            "to": backup_to,
            "evidence": (
                "Recorded as completed with a checksum, and the local archive is currently "
                "available."
            ),
        }
    elif backup is not None:
        backup_summary = {
            "state": "unverified",
            "label": "No verified backup is available",
            "detail": (
                "The latest completed record lacks a checksum or its local archive is unavailable."
            ),
            "created_at": None,
            "to": backup_to,
            "evidence": "Blockstead is not treating a completed database row alone as verified.",
        }
    else:
        backup_summary = {
            "state": "missing",
            "label": "No verified backup is recorded",
            "detail": "Create a verified backup before important changes.",
            "created_at": None,
            "to": backup_to,
            "evidence": "No completed backup record is available for this server.",
        }

    operation_to = f"/servers/{profile_id}/schedule"
    if next_operation is not None:
        next_at = next_operation.get("at")
        operation_summary = {
            "label": str(next_operation.get("label") or "Scheduled operation"),
            "detail": "This is the next operation calculated from the current schedule.",
            "at": str(next_at) if next_at is not None else None,
            "to": operation_to,
            "evidence": "Recorded schedule and one-time maintenance entries were evaluated now.",
        }
    else:
        operation_summary = {
            "label": "No operation scheduled",
            "detail": "There is no enabled upcoming server operation.",
            "at": None,
            "to": operation_to,
            "evidence": "No upcoming execution was calculated from the current schedule records.",
        }

    return {
        "playable": playable,
        "join": join_summary,
        "players": player_summary,
        "backup": backup_summary,
        "next_operation": operation_summary,
        "focus": _daily_focus(
            profile_id=profile_id,
            state=state_value,
            warnings=warnings,
            backup_verified=backup_verified,
            backup_present=backup is not None,
        ),
    }
