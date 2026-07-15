import time
from pathlib import Path

from fastapi.testclient import TestClient


def wait_for_state(client: TestClient, state: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get("/api/v1/server/state")
        if response.json()["state"] == state:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {state}")


def test_authenticated_fixture_lifecycle(client: TestClient, auth: dict[str, str]) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    scan = client.post("/api/v1/imports/scan", headers=auth, json={"path": str(fixture)})
    assert scan.status_code == 200
    assert scan.json()["plan"][0] == "Leave the folder in place"

    profile = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Fixture", "path": str(fixture)},
    )
    assert profile.status_code == 201
    assert profile.json()["is_fixture"] is True

    assert client.post(
        "/api/v1/server/start", headers=auth, json={"profile_id": profile.json()["id"]}
    ).status_code == 202
    wait_for_state(client, "RUNNING")
    command = client.post(
        "/api/v1/server/command",
        headers=auth,
        json={"command": "say API integration works"},
    )
    assert command.status_code == 202
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    assert wait_for_state(client, "STOPPED")["exit_code"] == 0


def test_logs_endpoint_names_the_profile_that_produced_each_line(
    client: TestClient, auth: dict[str, str]
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile_id = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(fixture)}
    ).json()["id"]

    assert (
        client.post(
            "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 202
    )
    wait_for_state(client, "RUNNING")
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")

    # The buffer outlives the run, so a reader needs every line to say who produced it.
    # ProcessManager covers the two-profile case; this pins the wire format the console
    # filters on, since only one profile may exist per server directory.
    events = client.get("/api/v1/server/logs", headers=auth).json()
    assert events
    assert {event["profile_id"] for event in events} == {profile_id}
