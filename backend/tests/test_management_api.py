import time
from pathlib import Path

from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def wait_for_state(client: TestClient, state: str) -> dict[str, object]:
    for _ in range(200):
        response = client.get("/api/v1/server/state")
        if response.json()["state"] == state:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {state}")


def wait_for_log(client: TestClient, text: str) -> None:
    for _ in range(200):
        lines = [event["line"] for event in client.get("/api/v1/server/logs").json()]
        if any(text in line for line in lines):
            return
        time.sleep(0.01)
    raise AssertionError(f"Log line containing {text!r} never appeared")


def import_fixture(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(FIXTURE)}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_profile_settings_view(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    response = client.get(f"/api/v1/profiles/{profile_id}/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["present"] is True
    by_key = {entry["key"]: entry for entry in body["settings"]}
    assert by_key["max-players"]["value"] == 20
    assert by_key["white-list"]["value"] is True
    assert by_key["motd"]["type"] == "string"
    assert "rcon.password" not in body["other_keys"]
    assert "custom-fixture-key" in body["other_keys"]
    assert "not-a-real-secret" not in response.text


def test_profile_players_view(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    response = client.get(f"/api/v1/profiles/{profile_id}/players")
    assert response.status_code == 200
    body = response.json()
    assert [player["name"] for player in body["allowlist"]["players"]] == [
        "Alex_Fixture",
        "Steve_Fixture",
    ]
    assert body["operators"]["players"][0]["level"] == 4
    assert body["bans"]["present"] is True
    assert body["bans"]["players"] == []


def test_profile_views_require_auth_and_existing_profile(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    unauthenticated = TestClient(client.app)
    assert unauthenticated.get(f"/api/v1/profiles/{profile_id}/settings").status_code == 401
    assert client.get("/api/v1/profiles/missing-id/players").status_code == 404


def test_player_action_requires_running_server(client: TestClient, auth: dict[str, str]) -> None:
    import_fixture(client, auth)
    response = client.post(
        "/api/v1/server/players",
        headers=auth,
        json={"action": "whitelist_add", "player": "New_Player"},
    )
    assert response.status_code == 409


def test_player_action_rejects_invalid_names(client: TestClient, auth: dict[str, str]) -> None:
    for player in ["ab", "has space", "way_too_long_for_minecraft", "semi;colon"]:
        response = client.post(
            "/api/v1/server/players",
            headers=auth,
            json={"action": "whitelist_add", "player": player},
        )
        assert response.status_code == 422, player


def test_player_action_lifecycle(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    assert (
        client.post(
            "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 202
    )
    wait_for_state(client, "RUNNING")
    response = client.post(
        "/api/v1/server/players",
        headers=auth,
        json={"action": "whitelist_add", "player": "New_Player"},
    )
    assert response.status_code == 202
    assert response.json()["command"] == "whitelist add New_Player"
    wait_for_log(client, "Added New_Player to the whitelist")
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")


def test_restart_reaches_running_with_new_pid(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    assert (
        client.post(
            "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 202
    )
    first = wait_for_state(client, "RUNNING")
    response = client.post("/api/v1/server/restart", headers=auth, json={"profile_id": profile_id})
    assert response.status_code == 202
    second = wait_for_state(client, "RUNNING")
    assert second["pid"] != first["pid"]
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")


def test_restart_requires_running_server(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    assert (
        client.post(
            "/api/v1/server/restart", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 409
    )


def test_system_metrics(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    response = client.get("/api/v1/system/metrics")
    assert response.status_code == 200
    body = response.json()
    assert body["memory"]["total_bytes"] > 0
    assert 0 <= body["disk"]["percent"] <= 100
    assert body["process"]["uptime_seconds"] is None

    assert (
        client.post(
            "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 202
    )
    wait_for_state(client, "RUNNING")
    running = client.get("/api/v1/system/metrics").json()
    assert running["process"]["uptime_seconds"] is not None
    assert running["process"]["memory_bytes"] is None or running["process"]["memory_bytes"] > 0
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")
