from blockstead.daily_summary import build_daily_summary


def summary(
    *,
    state: str = "RUNNING",
    players_available: bool = False,
    backup: dict[str, object] | None = None,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return build_daily_summary(
        profile={"id": "profile-1", "name": "Quiet world"},
        state={"value": state, "reason": "Observed state", "uptime_seconds": 20},
        join={"address": "192.168.1.5:25565", "local_only": False},
        players={
            "online": 2 if players_available else None,
            "max": 20,
            "available": players_available,
            "status_outcome": "responded" if players_available else "unreachable",
        },
        backup=backup,
        next_operation=None,
        warnings=warnings or [],
    )


def test_running_process_does_not_claim_players_can_connect_without_status_evidence() -> None:
    body = summary()

    playable = body["playable"]
    assert isinstance(playable, dict)
    assert playable["state"] == "running_unconfirmed"
    assert "does not prove" in str(playable["evidence"])


def test_completed_backup_requires_checksum_and_available_archive_to_be_verified() -> None:
    body = summary(
        backup={
            "status": "completed",
            "sha256": None,
            "archive_available": True,
            "created_at": "2026-08-08T12:00:00+00:00",
        }
    )

    backup = body["backup"]
    focus = body["focus"]
    assert isinstance(backup, dict)
    assert isinstance(focus, dict)
    assert backup["state"] == "unverified"
    assert backup["created_at"] is None
    assert focus["kind"] == "warning"
    assert focus["severity"] == "warning"


def test_completed_backup_rejects_a_malformed_recorded_checksum() -> None:
    body = summary(
        backup={
            "status": "completed",
            "sha256": "z" * 64,
            "archive_available": True,
            "created_at": "2026-08-08T12:00:00+00:00",
        }
    )

    backup = body["backup"]
    assert isinstance(backup, dict)
    assert backup["state"] == "unverified"


def test_daily_focus_selects_one_danger_before_lower_priority_warnings() -> None:
    body = summary(
        warnings=[
            {
                "code": "backup-missing",
                "title": "No backup",
                "detail": "Create one.",
                "to": "/backups",
                "severity": "warning",
            },
            {
                "code": "disk-space",
                "title": "Disk is nearly full",
                "detail": "Review storage.",
                "to": "/system",
                "severity": "danger",
            },
            {
                "code": "server-state",
                "title": "Server state warning",
                "detail": "Review state.",
                "to": "/console",
                "severity": "warning",
            },
        ]
    )

    focus = body["focus"]
    assert isinstance(focus, dict)
    assert focus == {
        "kind": "warning",
        "title": "Disk is nearly full",
        "detail": "Review storage.",
        "to": "/system",
        "severity": "danger",
        "evidence": (
            "Selected from the current disk-space evidence. This warning does not assert "
            "an unconfirmed cause."
        ),
    }
