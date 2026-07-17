import tarfile
import time
from pathlib import Path
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

from blockstead.backups import BackupError

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


def wait_for_log(client: TestClient, text: str) -> None:
    for _ in range(200):
        lines = [event["line"] for event in client.get("/api/v1/server/logs").json()]
        if any(text in line for line in lines):
            return
        time.sleep(0.01)
    raise AssertionError(f"Log line containing {text!r} never appeared")


def test_manual_backup_creates_private_archive_and_history(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)

    response = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["trigger"] == "manual"
    assert body["method"] == "world_archive"
    assert body["size_bytes"] > 0
    assert body["duration_ms"] >= 0
    assert body["result"] == "Protected world."
    archive_path = (
        client.app.state.settings.data_dir
        / "backups"
        / profile_id
        / body["file_name"]
    )
    assert archive_path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive_path) as archive:
        assert "world" in archive.getnames()

    history = client.get(f"/api/v1/profiles/{profile_id}/backups").json()
    assert history == [body]


def test_running_backup_flushes_and_reenables_saves(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    assert client.post(
        "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
    ).status_code == 202
    wait_for_state(client, "RUNNING")

    response = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)

    assert response.status_code == 201
    wait_for_log(client, "Received command: save-on")
    lines = [event["line"] for event in client.get("/api/v1/server/logs").json()]
    commands = [line.rsplit(": ", 1)[-1] for line in lines if "Received command:" in line]
    assert commands[-3:] == ["save-off", "save-all flush", "save-on"]
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")


def test_failed_running_backup_reenables_saves(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_id = import_fixture(client, auth)
    assert client.post(
        "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
    ).status_code == 202
    wait_for_state(client, "RUNNING")

    def fail_archive(*_: object) -> NoReturn:
        raise BackupError("The test archive failed safely.")

    monkeypatch.setattr("blockstead.app.create_backup_archive", fail_archive)
    response = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)

    assert response.status_code == 409
    wait_for_log(client, "Received command: save-on")
    history = client.get(f"/api/v1/profiles/{profile_id}/backups").json()
    assert history[0]["status"] == "failed"
    assert history[0]["result"] == "The test archive failed safely."
    assert client.post("/api/v1/server/stop", headers=auth).status_code == 202
    wait_for_state(client, "STOPPED")


def test_failed_backup_is_recorded(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_id = import_fixture(client, auth)

    def fail_archive(*_: object) -> NoReturn:
        raise BackupError("No world directory was found for this server.")

    monkeypatch.setattr("blockstead.app.create_backup_archive", fail_archive)

    response = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)

    assert response.status_code == 409
    history = client.get(f"/api/v1/profiles/{profile_id}/backups").json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["result"] == "No world directory was found for this server."
