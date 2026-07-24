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


def test_troubleshooting_catalog_and_assessment_are_authenticated(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)

    catalog = client.get("/api/v1/troubleshooting/problems")
    assert catalog.status_code == 200
    assert catalog.json()["version"] == "2026.07.1"

    assessment = client.post(
        f"/api/v1/profiles/{profile_id}/troubleshooting/assess",
        headers=auth,
        json={"problem_id": "player_cannot_join", "player_name": "New_Player"},
    )
    assert assessment.status_code == 200
    body = assessment.json()
    assert body["outcome"] == "problem_found"
    assert {check["id"] for check in body["checks"] if check["certainty"] == "confirmed"} >= {
        "server-running",
        "allowlist",
    }
    action = next(action for action in body["actions"] if action["id"] == "allowlist_add")
    assert action["available"] is False
    assert action["destructive"] is False

    client.cookies.clear()
    assert client.get("/api/v1/troubleshooting/problems").status_code == 401
    assert (
        client.post(
            f"/api/v1/profiles/{profile_id}/troubleshooting/assess",
            json={"problem_id": "local_connection"},
        ).status_code
        == 401
    )


def test_player_playbook_requires_a_valid_player_name(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)

    missing = client.post(
        f"/api/v1/profiles/{profile_id}/troubleshooting/assess",
        headers=auth,
        json={"problem_id": "player_cannot_join"},
    )
    invalid = client.post(
        f"/api/v1/profiles/{profile_id}/troubleshooting/assess",
        headers=auth,
        json={"problem_id": "player_cannot_join", "player_name": "bad name; stop"},
    )

    assert missing.status_code == 422
    assert invalid.status_code == 422


def test_troubleshooting_repair_rechecks_profile_and_records_the_bounded_action(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    stopped = client.post(
        f"/api/v1/profiles/{profile_id}/troubleshooting/repair",
        headers=auth,
        json={"action_id": "allowlist_add", "player_name": "New_Player"},
    )
    assert stopped.status_code == 409

    assert (
        client.post(
            "/api/v1/server/start",
            headers=auth,
            json={"profile_id": profile_id},
        ).status_code
        == 202
    )
    wait_for_state(client, "RUNNING")
    try:
        repaired = client.post(
            f"/api/v1/profiles/{profile_id}/troubleshooting/repair",
            headers=auth,
            json={"action_id": "allowlist_add", "player_name": "New_Player"},
        )
        assert repaired.status_code == 200
        assert repaired.json()["status"] == "accepted"
        activity = client.get("/api/v1/activity", headers=auth).json()["events"]
        assert any(
            event["category"] == "troubleshooting_repair" and "New_Player" in event["detail"]
            for event in activity
        )
    finally:
        client.post("/api/v1/server/stop", headers=auth)
        wait_for_state(client, "STOPPED")
