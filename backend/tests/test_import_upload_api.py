from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=tmp_path / "servers",
        allowed_origins="http://testserver",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def upload_files(client: TestClient, auth: dict[str, str], upload_id: str, files: list) -> object:
    return client.post(f"/api/v1/imports/uploads/{upload_id}/files", headers=auth, files=files)


def test_upload_import_creates_profile(client: TestClient, auth: dict[str, str]) -> None:
    started = client.post(
        "/api/v1/imports/uploads", headers=auth, json={"directory_name": "my-server"}
    )
    assert started.status_code == 201
    upload_id = started.json()["upload_id"]

    batch = upload_files(
        client,
        auth,
        upload_id,
        [
            ("files", ("JAR FILES/server.properties", b"motd=hi\n")),
            ("files", ("JAR FILES/server.jar", b"jar-bytes")),
            ("files", ("JAR FILES/world/level.dat", b"level")),
        ],
    )
    assert batch.status_code == 200
    assert batch.json()["received_files"] == 3

    finished = client.post(
        f"/api/v1/imports/uploads/{upload_id}/finish",
        headers=auth,
        json={"name": "New World", "directory_name": "my-server"},
    )
    assert finished.status_code == 201
    body = finished.json()
    assert body["distribution"] == "vanilla"

    target = Path(body["canonical_path"])
    assert target.name == "my-server"
    assert (target / "server.properties").read_bytes() == b"motd=hi\n"
    assert (target / "world" / "level.dat").is_file()
    assert not list(target.parent.glob(".upload-*"))

    profiles = client.get("/api/v1/profiles", headers=auth).json()
    assert [p["name"] for p in profiles] == ["New World"]


def test_upload_rejects_escaping_paths(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    started = client.post(
        "/api/v1/imports/uploads", headers=auth, json={"directory_name": "my-server"}
    )
    upload_id = started.json()["upload_id"]
    response = upload_files(client, auth, upload_id, [("files", ("../evil.txt", b"boom"))])
    assert response.status_code == 400
    root = tmp_path / "servers"
    assert not (root.parent / "evil.txt").exists()
    assert not list(root.glob(".upload-*"))


def test_upload_start_refuses_existing_folder(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    root = tmp_path / "servers"
    (root / "my-server").mkdir()
    response = client.post(
        "/api/v1/imports/uploads", headers=auth, json={"directory_name": "my-server"}
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["error"]["message"]


def test_upload_unknown_id_is_not_found(client: TestClient, auth: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/imports/uploads/deadbeefdeadbeefdeadbeefdeadbeef/finish",
        headers=auth,
        json={"name": "New World", "directory_name": "my-server"},
    )
    assert response.status_code == 404


def test_upload_cancel_removes_staging(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    started = client.post(
        "/api/v1/imports/uploads", headers=auth, json={"directory_name": "my-server"}
    )
    upload_id = started.json()["upload_id"]
    response = client.delete(f"/api/v1/imports/uploads/{upload_id}", headers=auth)
    assert response.status_code == 204
    assert not list((tmp_path / "servers").glob(".upload-*"))


def test_scan_permission_error_is_plain_language(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(path: Path, root: Path) -> object:
        raise PermissionError(13, "Permission denied", "/home/oem")

    monkeypatch.setattr("blockstead.app.scan_server", denied)
    response = client.post("/api/v1/imports/scan", headers=auth, json={"path": "/home/oem/x"})
    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "Errno" not in message
    assert "not allowed to read" in message


def test_scan_outside_root_names_the_root(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    response = client.post("/api/v1/imports/scan", headers=auth, json={"path": str(outside)})
    assert response.status_code == 400
    assert "can only scan folders inside" in response.json()["error"]["message"]
