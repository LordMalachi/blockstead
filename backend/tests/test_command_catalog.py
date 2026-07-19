import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.command_catalog import render_guided_command

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def import_fixture(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(FIXTURE)}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def wait_for_state(client: TestClient, state: str) -> None:
    for _ in range(200):
        if client.get("/api/v1/server/state").json()["state"] == state:
            return
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {state}")


def test_catalog_is_authenticated_and_marks_curated_coverage(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    response = client.get(f"/api/v1/profiles/{profile_id}/commands")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["complete"] is False
    assert {command["id"] for command in body["commands"]} >= {"give", "say", "ban"}

    unauthenticated = TestClient(client.app)
    assert unauthenticated.get(f"/api/v1/profiles/{profile_id}/commands").status_code == 401


def test_renderer_validates_values_and_builds_exact_command() -> None:
    command, safety = render_guided_command(
        "give", {"target": "Alex_Fixture", "item": "minecraft:diamond", "amount": 64}
    )
    assert command == "give Alex_Fixture minecraft:diamond 64"
    assert safety == "normal"

    with pytest.raises(ValueError, match="item identifier"):
        render_guided_command(
            "give", {"target": "Alex_Fixture", "item": "diamond; stop", "amount": 1}
        )
    with pytest.raises(ValueError, match="unexpected value"):
        render_guided_command("list", {"injected": "stop"})


def test_guided_command_requires_confirmation_and_running_owner(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    payload = {
        "profile_id": profile_id,
        "command_id": "ban",
        "values": {"target": "Alex_Fixture"},
    }
    assert (
        client.post("/api/v1/server/guided-command", headers=auth, json=payload).status_code == 409
    )

    assert (
        client.post(
            "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
        ).status_code
        == 202
    )
    wait_for_state(client, "RUNNING")
    review = client.post("/api/v1/server/guided-command", headers=auth, json=payload)
    assert review.status_code == 409
    assert "confirm" in review.json()["error"]["message"].lower()

    payload["confirmed"] = True
    sent = client.post("/api/v1/server/guided-command", headers=auth, json=payload)
    assert sent.status_code == 202
    assert sent.json()["command"] == "ban Alex_Fixture"
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")
