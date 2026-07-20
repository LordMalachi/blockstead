import shutil
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.backups import BackupError
from blockstead.config import Settings
from blockstead.models import BackupRecord

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
OWNER = {"username": "owner", "password": "correct horse battery staple"}


def owned_settings(tmp_path: Path) -> Settings:
    servers = tmp_path / "servers"
    servers.mkdir(exist_ok=True)
    return Settings(
        data_dir=tmp_path / "data",
        server_root=servers,
        allowed_origins="http://testserver",
    )


@pytest.fixture
def owned_client(tmp_path: Path) -> Iterator[TestClient]:
    """A client whose server root is writable, so restores may mutate worlds."""

    with TestClient(create_app(owned_settings(tmp_path))) as test_client:
        yield test_client


def owned_auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/admin", headers={"Origin": "http://testserver"}, json=OWNER
    )
    assert response.status_code == 201
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def import_writable_copy(client: TestClient, auth: dict[str, str]) -> tuple[str, Path]:
    server_root = client.app.state.settings.server_root
    copy = server_root / "restore-fixture"
    if not copy.exists():
        shutil.copytree(FIXTURE, copy)
    response = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Restorable", "path": str(copy)}
    )
    assert response.status_code == 201
    return str(response.json()["id"]), copy


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

    download = client.get(
        f"/api/v1/profiles/{profile_id}/backups/{body['id']}/download"
    )
    assert download.status_code == 200
    assert body["file_name"] in download.headers["content-disposition"]
    assert download.content == archive_path.read_bytes()

    history = client.get(f"/api/v1/profiles/{profile_id}/backups").json()
    assert history == [body]


def test_manual_backup_mirrors_to_every_approved_destination(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    profile_id = import_fixture(client, auth)
    first = tmp_path / "drive-a"
    second = tmp_path / "drive-b"
    first.mkdir()
    second.mkdir()
    policy = client.put(
        f"/api/v1/profiles/{profile_id}/backup-policy",
        headers=auth,
        json={
            "keep_count": 10,
            "keep_days": None,
            "max_total_mb": None,
            "redundancy_enabled": True,
            "destinations": [str(first), str(second)],
        },
    )
    assert policy.status_code == 200

    backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()

    assert backup["status"] == "completed"
    assert "mirrored to 2 approved destinations" in backup["result"].lower()
    for destination in (first, second):
        mirrored = destination / "blockstead-backups" / profile_id
        assert (mirrored / backup["file_name"]).is_file()


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

    def fail_archive(*_: object, **__: object) -> NoReturn:
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

    def fail_archive(*_: object, **__: object) -> NoReturn:
        raise BackupError("No world directory was found for this server.")

    monkeypatch.setattr("blockstead.app.create_backup_archive", fail_archive)

    response = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)

    assert response.status_code == 409
    history = client.get(f"/api/v1/profiles/{profile_id}/backups").json()
    assert len(history) == 1
    assert history[0]["status"] == "failed"
    assert history[0]["result"] == "No world directory was found for this server."


def test_restore_preview_and_roundtrip_preserves_previous_world(
    owned_client: TestClient,
) -> None:
    auth = owned_auth(owned_client)
    profile_id, server = import_writable_copy(owned_client, auth)
    (server / "world" / "level.dat").write_bytes(b"first day")

    backup = owned_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()
    assert backup["status"] == "completed"
    assert backup["archive_available"] is True
    assert backup["included_paths"] == ["world"]
    assert isinstance(backup["sha256"], str) and len(backup["sha256"]) == 64

    (server / "world" / "level.dat").write_bytes(b"after the accident")
    (server / "world" / "extra.dat").write_bytes(b"newer chunk data")

    preview = owned_client.get(
        f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore-preview",
        headers=auth,
    )
    assert preview.status_code == 200
    plan = preview.json()
    assert plan["verified"] is True
    assert plan["worlds_replaced"] == ["world"]
    assert plan["can_restore"] is True
    assert plan["blockers"] == []
    assert plan["sha256"] == backup["sha256"]

    response = owned_client.post(
        f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore", headers=auth
    )
    assert response.status_code == 200
    result = response.json()
    assert result["restored_paths"] == ["world"]
    assert len(result["preserved_paths"]) == 1
    preserved = server / result["preserved_paths"][0]
    assert preserved.name.startswith("world.pre-restore-")
    assert (server / "world" / "level.dat").read_bytes() == b"first day"
    assert not (server / "world" / "extra.dat").exists()
    assert (preserved / "extra.dat").read_bytes() == b"newer chunk data"


def test_restore_is_refused_while_the_server_runs(owned_client: TestClient) -> None:
    auth = owned_auth(owned_client)
    profile_id, server = import_writable_copy(owned_client, auth)
    (server / "world" / "level.dat").write_bytes(b"protected")
    backup = owned_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()

    assert owned_client.post(
        "/api/v1/server/start", headers=auth, json={"profile_id": profile_id}
    ).status_code == 202
    wait_for_state(owned_client, "RUNNING")
    try:
        preview = owned_client.get(
            f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore-preview",
            headers=auth,
        ).json()
        assert preview["can_restore"] is False
        assert any("Stop this server" in blocker for blocker in preview["blockers"])

        response = owned_client.post(
            f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore", headers=auth
        )
        assert response.status_code == 409
        assert "Stop this server" in response.json()["error"]["message"]
        assert (server / "world" / "level.dat").read_bytes() == b"protected"
    finally:
        assert owned_client.post("/api/v1/server/stop", headers=auth).status_code == 202
        wait_for_state(owned_client, "STOPPED")


def test_restore_rejects_a_tampered_archive(owned_client: TestClient) -> None:
    auth = owned_auth(owned_client)
    profile_id, server = import_writable_copy(owned_client, auth)
    (server / "world" / "level.dat").write_bytes(b"authentic")
    backup = owned_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()

    archive_path = (
        owned_client.app.state.settings.data_dir
        / "backups"
        / profile_id
        / backup["file_name"]
    )
    body = bytearray(archive_path.read_bytes())
    body[len(body) // 2] ^= 0xFF
    archive_path.write_bytes(bytes(body))

    preview = owned_client.get(
        f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore-preview",
        headers=auth,
    )
    assert preview.status_code == 409
    assert "checksum" in preview.json()["error"]["message"]

    response = owned_client.post(
        f"/api/v1/profiles/{profile_id}/backups/{backup['id']}/restore", headers=auth
    )
    assert response.status_code == 409
    assert "checksum" in response.json()["error"]["message"]
    assert (server / "world" / "level.dat").read_bytes() == b"authentic"


def test_backup_policy_roundtrip_applies_retention(owned_client: TestClient) -> None:
    auth = owned_auth(owned_client)
    profile_id, server = import_writable_copy(owned_client, auth)
    (server / "world" / "level.dat").write_bytes(b"generation one")

    policy = owned_client.get(
        f"/api/v1/profiles/{profile_id}/backup-policy", headers=auth
    ).json()
    assert policy == {
        "keep_count": 10,
        "keep_days": None,
        "max_total_mb": None,
        "redundancy_enabled": False,
        "destinations": [],
    }

    first = owned_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()
    second = owned_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).json()
    assert first["status"] == second["status"] == "completed"

    updated = owned_client.put(
        f"/api/v1/profiles/{profile_id}/backup-policy",
        headers=auth,
        json={
            "keep_count": 1,
            "keep_days": None,
            "max_total_mb": None,
            "redundancy_enabled": False,
            "destinations": [],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["keep_count"] == 1
    assert updated.json()["expired_now"] == 1

    history = {
        record["id"]: record
        for record in owned_client.get(
            f"/api/v1/profiles/{profile_id}/backups", headers=auth
        ).json()
    }
    assert history[second["id"]]["status"] == "completed"
    assert history[first["id"]]["status"] == "expired"
    assert history[first["id"]]["archive_available"] is False
    assert "Removed by the retention policy" in history[first["id"]]["result"]
    backups_dir = owned_client.app.state.settings.data_dir / "backups" / profile_id
    assert not (backups_dir / first["file_name"]).exists()
    assert (backups_dir / second["file_name"]).exists()

    refused = owned_client.post(
        f"/api/v1/profiles/{profile_id}/backups/{first['id']}/restore", headers=auth
    )
    assert refused.status_code == 409
    assert "retention policy" in refused.json()["error"]["message"]

    invalid = owned_client.put(
        f"/api/v1/profiles/{profile_id}/backup-policy",
        headers=auth,
        json={"keep_count": 0},
    )
    assert invalid.status_code == 422


def test_interrupted_backup_is_marked_failed_after_restart(tmp_path: Path) -> None:
    settings = owned_settings(tmp_path)
    with TestClient(create_app(settings)) as first_client:
        auth = owned_auth(first_client)
        profile_id, _ = import_writable_copy(first_client, auth)
        with first_client.app.state.session_factory() as db:
            db.add(BackupRecord(profile_id=profile_id, trigger="manual"))
            db.commit()

    with TestClient(create_app(owned_settings(tmp_path))) as second_client:
        login = second_client.post(
            "/api/v1/auth/login", headers={"Origin": "http://testserver"}, json=OWNER
        )
        assert login.status_code == 200
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": login.json()["csrf_token"],
        }
        history = second_client.get(
            f"/api/v1/profiles/{profile_id}/backups", headers=headers
        ).json()
        interrupted = [
            record for record in history if record["status"] == "failed"
        ]
        assert len(interrupted) == 1
        assert interrupted[0]["result"] == "Blockstead stopped before this backup completed."
