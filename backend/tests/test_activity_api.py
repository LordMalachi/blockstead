import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from blockstead.activity import event_payload
from blockstead.models import Administrator, AuditEvent, AutomationRun, Profile

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def test_skipped_activity_is_a_warning_instead_of_success() -> None:
    event = AuditEvent(
        admin_id="admin-1",
        category="automation_start",
        result="skipped",
        safe_detail="Another server is already running on this host.",
        created_at=datetime.now(UTC),
    )

    assert event_payload(event)["severity"] == "warning"


def test_refused_activity_is_a_warning_instead_of_success() -> None:
    event = AuditEvent(
        admin_id="admin-1",
        category="maintenance_schedule",
        result="refused",
        safe_detail="The reviewed evidence changed before scheduling.",
        created_at=datetime.now(UTC),
    )

    assert event_payload(event)["severity"] == "warning"


def import_fixture(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Activity world", "path": str(FIXTURE)},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_activity_is_profile_aware_and_downloads_a_focused_report(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    assert client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).status_code == 201

    response = client.get(f"/api/v1/activity?profile_id={profile_id}&category=backup")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    event = body["events"][0]
    assert event["category"] == "manual_backup"
    assert event["profile"] == {"id": profile_id, "name": "Activity world"}
    assert event["actor"] == "owner"
    assert event["recovery_to"].endswith("/backups")

    report = client.get(event["report_url"])
    assert report.status_code == 200
    assert report.headers["content-disposition"].startswith(
        f'attachment; filename="blockstead-event-{event["id"][:8]}-'
    )
    payload = json.loads(report.content)
    assert payload["focus_event"]["id"] == event["id"]
    assert payload["focus_event"]["profile_id"] == profile_id
    assert "focus_log_window" in payload


def test_local_notification_preferences_can_be_changed_and_acknowledged(
    client: TestClient, auth: dict[str, str]
) -> None:
    defaults = client.get("/api/v1/notification-preferences").json()
    assert defaults == {
        "server_crashes": True,
        "failed_backups": True,
        "failed_automations": True,
        "low_disk_space": True,
        "completed_updates": True,
        "show_player_avatars": False,
        "last_seen_at": None,
    }

    changed = client.put(
        "/api/v1/notification-preferences",
        headers=auth,
        json={
            "server_crashes": False,
            "failed_backups": True,
            "failed_automations": False,
            "low_disk_space": False,
            "completed_updates": True,
            "show_player_avatars": True,
        },
    )
    assert changed.status_code == 200
    assert changed.json()["server_crashes"] is False
    assert changed.json()["failed_automations"] is False
    assert changed.json()["low_disk_space"] is False
    assert changed.json()["show_player_avatars"] is True

    assert client.post("/api/v1/notifications/acknowledge", headers=auth).status_code == 204
    assert client.get("/api/v1/notification-preferences").json()["last_seen_at"] is not None


def test_activity_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/activity").status_code == 401
    assert client.get("/api/v1/activity/not-here/incident").status_code == 401
    assert client.get("/api/v1/notification-preferences").status_code == 401
    assert client.get("/api/v1/notifications").status_code == 401


def test_failed_automation_and_unsafe_profile_directory_raise_local_alerts(
    client: TestClient, auth: dict[str, str]
) -> None:
    root = client.app.state.settings.server_root
    with client.app.state.session_factory() as db:
        unsafe = Profile(
            name="Legacy root import",
            server_directory=str(root),
            distribution="unknown",
            minecraft_version=None,
        )
        db.add(unsafe)
        db.flush()
        db.add(
            AutomationRun(
                profile_id=unsafe.id,
                trigger="scheduled",
                action="maintenance",
                status="failed",
                steps="[]",
                detail="Linux host power helper failed with exit code 7",
                duration_ms=10,
                started_at=datetime.now(UTC),
            )
        )
        db.commit()

    alerts = client.get("/api/v1/notifications", headers=auth).json()["alerts"]
    kinds = {alert["kind"] for alert in alerts}
    assert "failed_automation" in kinds
    assert "unsafe_profile_directory" in kinds


def test_incident_requires_an_existing_anchor(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/api/v1/activity/not-here/incident").status_code == 404


def test_incident_is_chronological_profile_scoped_and_cautious(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    now = datetime.now(UTC)
    logging.getLogger("blockstead.incident-test").warning(
        "Nearby test warning password=not-for-the-incident"
    )
    with client.app.state.session_factory() as db:
        admin_id = db.scalar(select(Administrator.id))
        assert admin_id is not None
        imported = db.scalar(
            select(AuditEvent).where(
                AuditEvent.profile_id == profile_id,
                AuditEvent.category == "profile_import",
            )
        )
        assert imported is not None
        imported.created_at = now - timedelta(minutes=30)
        other = Profile(
            name="Other world",
            server_directory=str(FIXTURE.parent / "other-incident-world"),
            distribution="vanilla",
            minecraft_version="1.21.8",
        )
        db.add(other)
        db.flush()
        before = AuditEvent(
            admin_id=admin_id,
            profile_id=profile_id,
            category="schedule_update",
            result="success",
            safe_detail="Recorded a schedule before the symptom",
            created_at=now - timedelta(minutes=5),
        )
        anchor = AuditEvent(
            admin_id=admin_id,
            profile_id=profile_id,
            category="server_crash",
            result="failed",
            safe_detail="The managed process exited unexpectedly",
            created_at=now,
        )
        after = AuditEvent(
            admin_id=admin_id,
            profile_id=profile_id,
            category="settings_update",
            result="success",
            safe_detail="Recorded settings after the symptom",
            created_at=now + timedelta(minutes=5),
        )
        db.add_all(
            [
                before,
                anchor,
                after,
                AuditEvent(
                    admin_id=admin_id,
                    profile_id=profile_id,
                    category="player_action",
                    result="accepted",
                    safe_detail="Excluded player activity",
                    created_at=now + timedelta(minutes=1),
                ),
                AuditEvent(
                    admin_id=admin_id,
                    profile_id=other.id,
                    category="manual_backup",
                    result="success",
                    safe_detail="Excluded other-profile backup",
                    created_at=now + timedelta(minutes=2),
                ),
            ]
        )
        db.commit()
        anchor_id = anchor.id

    response = client.get(f"/api/v1/activity/{anchor_id}/incident")

    assert response.status_code == 200
    body = response.json()
    assert body["anchor"]["id"] == anchor_id
    assert body["anchor"]["report_url"].endswith(f"/{anchor_id}/report")
    assert [event["category"] for event in body["recorded_facts"]] == [
        "schedule_update",
        "settings_update",
    ]
    assert all(event["profile"]["id"] == profile_id for event in body["recorded_facts"])
    assert "proximity does not establish" in body["observed_timing"]["detail"]
    assert body["possible_explanation"]["state"] == "unconfirmed"
    assert "not proof of causation" in body["possible_explanation"]["detail"]
    assert body["log_context"]["state"] == "available"
    messages = [entry["message"] for entry in body["log_context"]["entries"]]
    assert any("password=[redacted]" in message for message in messages)
    assert all("not-for-the-incident" not in message for message in messages)
    assert body["safe_next_action"]["to"].endswith(f"/{profile_id}/console")
