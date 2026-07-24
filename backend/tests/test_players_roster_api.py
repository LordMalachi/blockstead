import time
from pathlib import Path

from fastapi.testclient import TestClient


def wait_for_state(client: TestClient, state: str) -> dict[str, object]:
    for _ in range(200):
        response = client.get("/api/v1/server/state")
        if response.json()["state"] == state:
            return response.json()
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {state}")


def wait_for_roster(
    client: TestClient, profile_id: str, player: str, *, tracked_online: bool
) -> dict[str, object]:
    for _ in range(200):
        roster = client.get(f"/api/v1/profiles/{profile_id}/players/roster").json()
        entry = next((item for item in roster["entries"] if item["name"] == player), None)
        if entry is not None and entry["tracked_online"] is tracked_online:
            return entry
        time.sleep(0.01)
    raise AssertionError(f"{player} did not reach tracked_online={tracked_online}")


def import_and_start(client: TestClient, auth: dict[str, str]) -> str:
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
    return profile_id


def test_roster_lists_allowlist_and_operators_before_a_server_ever_starts(
    client: TestClient, auth: dict[str, str]
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile_id = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(fixture)}
    ).json()["id"]

    response = client.get(f"/api/v1/profiles/{profile_id}/players/roster")
    assert response.status_code == 200
    body = response.json()
    assert body["status_available"] is False
    assert body["online_count"] is None
    names = {entry["name"] for entry in body["entries"]}
    assert "Alex_Fixture" in names
    assert "Steve_Fixture" in names
    alex = next(entry for entry in body["entries"] if entry["name"] == "Alex_Fixture")
    assert alex["allowlisted"] is True
    assert alex["operator"] is True
    assert alex["tracked_online"] is False
    assert alex["last_seen"] is None


def test_roster_tracks_a_join_then_a_kick_closes_the_session(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_and_start(client, auth)
    try:
        assert (
            client.post(
                "/api/v1/server/command",
                headers=auth,
                json={"command": "simulate-join Steve_Fixture"},
            ).status_code
            == 202
        )
        online_entry = wait_for_roster(client, profile_id, "Steve_Fixture", tracked_online=True)
        assert online_entry["last_seen"] is None
        assert online_entry["session_seconds"] is not None

        kicked = client.post(
            "/api/v1/server/players",
            headers=auth,
            json={"action": "kick", "player": "Steve_Fixture"},
        )
        assert kicked.status_code == 202
        assert kicked.json()["command"] == "kick Steve_Fixture"

        offline_entry = wait_for_roster(client, profile_id, "Steve_Fixture", tracked_online=False)
        assert offline_entry["last_seen"] is not None
        assert offline_entry["session_seconds"] is not None
    finally:
        client.post("/api/v1/server/stop", headers=auth)
        wait_for_state(client, "STOPPED")


def test_kick_is_recorded_as_a_player_action(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_and_start(client, auth)
    try:
        client.post(
            "/api/v1/server/players",
            headers=auth,
            json={"action": "kick", "player": "Alex_Fixture"},
        )
        events = client.get("/api/v1/activity", headers=auth, params={"category": "player"}).json()
        detail = " ".join(event["detail"] for event in events["events"])
        assert "kick" in detail
        assert "Alex_Fixture" in detail
        assert profile_id  # the profile exists; activity here is workspace-scoped, not per-profile
    finally:
        client.post("/api/v1/server/stop", headers=auth)
        wait_for_state(client, "STOPPED")


def test_roster_requires_authentication(client: TestClient, auth: dict[str, str]) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile_id = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(fixture)}
    ).json()["id"]
    client.cookies.clear()
    response = client.get(f"/api/v1/profiles/{profile_id}/players/roster")
    assert response.status_code == 401
