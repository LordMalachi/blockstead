import time
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def import_fixture(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Fixture", "path": str(FIXTURE)},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def wait_for_state(client: TestClient, expected: str) -> None:
    for _ in range(200):
        if client.get("/api/v1/server/state").json()["state"] == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {expected}.")


def preflight(
    client: TestClient, auth: dict[str, str], profile_id: str, change_id: str
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=auth,
        json={"change_id": change_id},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def finding(plan: dict[str, object], finding_id: str) -> dict[str, object]:
    findings = plan["findings"]
    assert isinstance(findings, list)
    return next(item for item in findings if item["id"] == finding_id)


def test_the_change_catalog_and_preflight_require_a_session(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)

    catalog = client.get("/api/v1/maintenance/changes")
    assert catalog.status_code == 200
    assert catalog.json()["version"] == "2026.07.1"
    assert len(catalog.json()["changes"]) == 5

    client.cookies.clear()
    assert client.get("/api/v1/maintenance/changes").status_code == 401
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/preflight",
            json={"change_id": "world_files"},
        ).status_code
        == 401
    )


def test_a_preflight_rejects_an_unknown_change_and_an_unknown_profile(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/preflight",
            headers=auth,
            json={"change_id": "reformat_the_disk"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/profiles/does-not-exist/maintenance/preflight",
            headers=auth,
            json={"change_id": "world_files"},
        ).status_code
        == 404
    )


def test_a_stopped_server_without_a_backup_still_gets_a_required_protection_step(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "world_files")

    assert plan["readiness"] in {"ready", "ready_with_warnings"}
    assert plan["protection"]["verified"] is False
    assert plan["restart"] == "required"
    backup_step = next(step for step in plan["steps"] if step["id"] == "backup")
    assert backup_step["requirement"] == "required"
    assert finding(plan, "protection-point")["status"] == "attention"
    # Nothing may be presented as automatic: every step is the owner's to run.
    assert {step["performed_by"] for step in plan["steps"]} == {"owner"}


def test_a_preflight_verifies_the_newest_backup_rather_than_trusting_it(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    created = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)
    assert created.status_code == 201, created.text
    record = created.json()
    assert record["status"] == "completed", record["result"]

    plan = preflight(client, auth, profile_id, "world_files")
    assert plan["protection"]["verified"] is True
    assert plan["protection"]["backup_id"] == record["id"]
    assert finding(plan, "protection-point")["status"] == "ready"

    # Corrupt the stored archive; the same preflight must stop calling it protection.
    data_dir = Path(client.app.state.settings.data_dir)
    archive = data_dir / "backups" / profile_id / record["file_name"]
    assert archive.is_file()
    archive.write_bytes(b"not the archive Blockstead wrote")

    damaged = preflight(client, auth, profile_id, "world_files")
    assert damaged["protection"]["verified"] is False
    assert finding(damaged, "protection-point")["status"] == "attention"
    assert (
        next(step for step in damaged["steps"] if step["id"] == "backup")["requirement"]
        == "required"
    )


def test_a_running_server_plans_an_announcement_and_a_stop(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    started = client.post(
        "/api/v1/server/start", headers=auth, json={"profile_id": profile_id, "mode": "normal"}
    )
    assert started.status_code == 202, started.text
    wait_for_state(client, "RUNNING")
    try:
        plan = preflight(client, auth, profile_id, "extension_update")
        step_ids = [step["id"] for step in plan["steps"]]
        assert step_ids[:2] == ["announce", "save"]
        assert "stop" in step_ids
        assert next(step for step in plan["steps"] if step["id"] == "stop")["requirement"] == (
            "required"
        )
        assert finding(plan, "server-state")["status"] == "attention"
    finally:
        client.post("/api/v1/server/stop", headers=auth)
        wait_for_state(client, "STOPPED")


def test_a_server_upgrade_is_blocked_until_a_source_can_be_verified(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "server_upgrade")
    assert plan["readiness"] == "blocked"
    assert plan["blockers"]
    assert finding(plan, "upgrade-target")["status"] == "blocked"
    # The practice server has no published releases, so its compatibility is a
    # statement of fact rather than a stop.
    assert finding(plan, "compatibility")["status"] == "info"


def test_the_upgrade_review_never_calls_the_practice_server_current(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    response = client.get(f"/api/v1/profiles/{profile_id}/maintenance/upgrades", headers=auth)
    assert response.status_code == 200
    review = response.json()
    assert review["source"] == "not_supported"
    assert review["up_to_date"] is None
    assert review["installable_here"] is False
    assert review["candidates"] == []

    assert (
        client.get("/api/v1/profiles/does-not-exist/maintenance/upgrades", headers=auth).status_code
        == 404
    )
    client.cookies.clear()
    assert (
        client.get(f"/api/v1/profiles/{profile_id}/maintenance/upgrades").status_code == 401
    )


def future_run_at(days: int = 1) -> str:
    return (datetime.now().astimezone() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def pending_events(
    client: TestClient, auth: dict[str, str], profile_id: str
) -> list[dict[str, object]]:
    schedules = client.get("/api/v1/schedules", headers=auth).json()
    return [
        event
        for entry in schedules
        if entry["profile_id"] == profile_id
        for event in entry["one_time_events"]
    ]


def test_a_reviewed_plan_can_be_booked_as_a_maintenance_window(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "world_files")
    run_at = future_run_at()

    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=auth,
        json={
            "change_id": "world_files",
            "plan_id": plan["plan_id"],
            "run_at": run_at,
            "only_when_empty": True,
        },
    )
    assert response.status_code == 201, response.text
    booked = response.json()
    assert booked["run_at"] == run_at
    assert booked["plan_id"] == plan["plan_id"]
    # A reviewed plan always protects first, so the window is not allowed to skip it.
    assert booked["backup_before_stop"] is True

    assert any(event["run_at"] == run_at for event in pending_events(client, auth, profile_id))

    activity = client.get("/api/v1/activity", headers=auth).json()
    recorded = next(
        event for event in activity["events"] if event["category"] == "maintenance_schedule"
    )
    assert recorded["result"] == "success"
    assert plan["plan_id"] in recorded["detail"]


def test_a_plan_whose_evidence_moved_on_is_refused_with_the_fresh_review(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    stale = preflight(client, auth, profile_id, "world_files")

    # Creating a backup changes the protection point, which is part of the
    # evidence the plan was reviewed against.
    assert client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).status_code == 201

    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=auth,
        json={
            "change_id": "world_files",
            "plan_id": stale["plan_id"],
            "run_at": future_run_at(),
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "stale_plan"
    assert body["plan"]["plan_id"] != stale["plan_id"]
    assert body["plan"]["protection"]["verified"] is True

    # Nothing was booked, and the refusal itself is recorded.
    assert pending_events(client, auth, profile_id) == []
    activity = client.get("/api/v1/activity", headers=auth).json()
    refusal = next(
        event
        for event in activity["events"]
        if event["category"] == "maintenance_schedule" and event["result"] == "refused"
    )
    assert "stale plan" in refusal["detail"]

    # The fresh plan books successfully, so the refusal is a re-review, not a dead end.
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/schedule",
            headers=auth,
            json={
                "change_id": "world_files",
                "plan_id": body["plan"]["plan_id"],
                "run_at": future_run_at(2),
            },
        ).status_code
        == 201
    )


def test_a_blocked_plan_cannot_be_scheduled(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "server_upgrade")
    assert plan["readiness"] == "blocked"

    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=auth,
        json={
            "change_id": "server_upgrade",
            "plan_id": plan["plan_id"],
            "run_at": future_run_at(),
        },
    )
    assert response.status_code == 409
    assert "blocked" in response.json()["error"]["message"]


def test_scheduling_rejects_a_past_time_a_bad_plan_id_and_no_session(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "world_files")
    body = {
        "change_id": "world_files",
        "plan_id": plan["plan_id"],
        "run_at": "2020-01-01T10:00",
    }
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/schedule", headers=auth, json=body
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/schedule",
            headers=auth,
            json={**body, "plan_id": "not-a-fingerprint", "run_at": future_run_at()},
        ).status_code
        == 422
    )
    client.cookies.clear()
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/schedule",
            json={**body, "run_at": future_run_at()},
        ).status_code
        == 401
    )


def test_every_preflight_is_recorded_in_activity(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    plan = preflight(client, auth, profile_id, "extension_install")

    activity = client.get("/api/v1/activity", headers=auth).json()
    recorded = next(
        event for event in activity["events"] if event["category"] == "maintenance_preflight"
    )
    assert recorded["group"] == "maintenance"
    assert recorded["title"] == "Maintenance change reviewed"
    assert recorded["recovery_to"] == f"/servers/{profile_id}/maintenance"
    assert plan["plan_id"] in recorded["detail"]
    assert plan["readiness"] in recorded["detail"]
