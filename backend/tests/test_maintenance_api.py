import time
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
    assert finding(plan, "compatibility")["status"] == "blocked"


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
