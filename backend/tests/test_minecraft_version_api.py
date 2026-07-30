import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


@pytest.fixture
def server_root(tmp_path: Path) -> Path:
    root = tmp_path / "servers"
    root.mkdir()
    return root


@pytest.fixture
def client(tmp_path: Path, server_root: Path) -> TestClient:
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=server_root,
        allowed_origins="http://testserver",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def make_server(root: Path, name: str, version: str | None = None) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    if version is None:
        (folder / "server.jar").write_bytes(b"unreadable")
    else:
        with zipfile.ZipFile(folder / "server.jar", "w") as archive:
            archive.writestr("version.json", json.dumps({"id": version}))
    return folder


def import_folder(client: TestClient, auth: dict[str, str], folder: Path) -> dict[str, object]:
    response = client.post(
        "/api/v1/profiles", headers=auth, json={"name": folder.name, "path": str(folder)}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_import_records_the_version_from_the_folder(
    client: TestClient, auth: dict[str, str], server_root: Path
) -> None:
    created = import_folder(client, auth, make_server(server_root, "friends-smp", "1.21.4"))
    assert created["minecraft_version"] == "1.21.4"


def test_a_profile_imported_without_a_version_is_identified_later(
    client: TestClient, auth: dict[str, str], server_root: Path
) -> None:
    # Model an older import: the profile exists with no version, and the folder
    # only becomes identifiable afterwards.
    folder = make_server(server_root, "old-import")
    profile_id = import_folder(client, auth, folder)["id"]
    assert client.get("/api/v1/profiles").json()[0]["minecraft_version"] is None

    with zipfile.ZipFile(folder / "server.jar", "w") as archive:
        archive.writestr("version.json", json.dumps({"id": "1.20.1"}))

    listed = client.get("/api/v1/profiles").json()
    assert listed[0]["id"] == profile_id
    assert listed[0]["minecraft_version"] == "1.20.1"


def test_an_unidentifiable_version_can_be_recorded_by_hand(
    client: TestClient, auth: dict[str, str], server_root: Path
) -> None:
    profile_id = import_folder(client, auth, make_server(server_root, "mystery"))["id"]
    response = client.put(
        f"/api/v1/profiles/{profile_id}/minecraft-version",
        headers=auth,
        json={"minecraft_version": "1.18.2"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["minecraft_version"] == "1.18.2"
    assert client.get("/api/v1/profiles").json()[0]["minecraft_version"] == "1.18.2"
    categories = [event["category"] for event in client.get("/api/v1/activity").json()["events"]]
    assert "profile_version" in categories


def test_a_recorded_version_is_never_a_path_or_a_command(
    client: TestClient, auth: dict[str, str], server_root: Path
) -> None:
    profile_id = import_folder(client, auth, make_server(server_root, "mystery"))["id"]
    for value in ["../../etc", "1.21.4; rm -rf /", "", "latest"]:
        response = client.put(
            f"/api/v1/profiles/{profile_id}/minecraft-version",
            headers=auth,
            json={"minecraft_version": value},
        )
        assert response.status_code == 422, value


def test_recording_a_version_requires_a_signed_in_owner(
    client: TestClient, auth: dict[str, str], server_root: Path
) -> None:
    profile_id = import_folder(client, auth, make_server(server_root, "mystery"))["id"]
    response = client.put(
        f"/api/v1/profiles/{profile_id}/minecraft-version",
        json={"minecraft_version": "1.18.2"},
    )
    assert response.status_code in {401, 403}
