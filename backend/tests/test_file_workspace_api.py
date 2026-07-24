import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Path, dict[str, str], str]]:
    root = tmp_path / "servers"
    settings = Settings(
        data_dir=tmp_path / "data", server_root=root, allowed_origins="http://testserver"
    )
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v1/setup/admin",
            headers={"Origin": "http://testserver"},
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": setup.json()["csrf_token"],
        }
        folder = root / "fabric-server"
        (folder / "world").mkdir(parents=True)
        (folder / "world" / "level.dat").write_bytes(b"world-data")
        (folder / "logs").mkdir()
        (folder / "logs" / "latest.log").write_text("hello\n", encoding="utf-8")
        (folder / "mods").mkdir()
        (folder / "server.properties").write_text("motd=Hi\n", encoding="utf-8")
        (folder / "fabric-server-launch.jar").write_bytes(b"launcher")
        created = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fabric", "path": str(folder)},
        )
        assert created.status_code == 201, created.text
        yield client, folder, headers, created.json()["id"]


def test_lists_config_category(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, _headers, profile_id = api
    response = client.get(f"/api/v1/profiles/{profile_id}/files/config")
    assert response.status_code == 200
    body = response.json()
    assert body["writable"] is True
    names = {entry["name"] for entry in body["entries"]}
    assert "server.properties" in names
    # world/logs/mods have their own categories with their own protections;
    # config excludes them rather than duplicating (and bypassing) those.
    assert "mods" not in names
    assert "world" not in names
    assert "logs" not in names


def test_config_category_cannot_reach_into_world_via_path(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, _folder, _headers, profile_id = api
    response = client.get(
        f"/api/v1/profiles/{profile_id}/files/config/content",
        params={"path": "world/level.dat"},
    )
    assert response.status_code == 404


def test_lists_world_category_shows_only_recognized_folders(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, folder, _headers, profile_id = api
    (folder / "not_a_world_folder").mkdir()
    response = client.get(f"/api/v1/profiles/{profile_id}/files/world")
    assert response.status_code == 200
    names = {entry["name"] for entry in response.json()["entries"]}
    assert names == {"world"}


def test_unknown_category_is_rejected(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, _headers, profile_id = api
    response = client.get(f"/api/v1/profiles/{profile_id}/files/nope")
    assert response.status_code == 404


def test_extensions_category_requires_a_loader(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, folder, headers, _profile_id = api
    vanilla = folder.parent / "vanilla-server"
    vanilla.mkdir()
    (vanilla / "server.properties").write_text("motd=Hi\n", encoding="utf-8")
    (vanilla / "server.jar").write_bytes(b"jar")
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Vanilla", "path": str(vanilla)}
    )
    profile_id = created.json()["id"]
    response = client.get(f"/api/v1/profiles/{profile_id}/files/extensions")
    assert response.status_code == 404


def test_reads_and_edits_config_file_with_snapshot(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, folder, headers, profile_id = api
    content = client.get(
        f"/api/v1/profiles/{profile_id}/files/config/content",
        params={"path": "server.properties"},
    )
    assert content.status_code == 200
    body = content.json()
    assert body["content"] == "motd=Hi\n"
    assert body["editable"] is True

    preview = client.post(
        f"/api/v1/profiles/{profile_id}/files/config/content/preview",
        headers=headers,
        json={"path": "server.properties", "revision": body["revision"], "content": "motd=Bye\n"},
    )
    assert preview.status_code == 200
    assert preview.json()["valid"] is True
    assert preview.json()["no_changes"] is False

    applied = client.put(
        f"/api/v1/profiles/{profile_id}/files/config/content",
        headers=headers,
        json={"path": "server.properties", "revision": body["revision"], "content": "motd=Bye\n"},
    )
    assert applied.status_code == 200
    result = applied.json()
    assert (folder / "server.properties").read_text(encoding="utf-8") == "motd=Bye\n"
    snapshot = (
        client.app.state.settings.data_dir
        / "file-snapshots"
        / profile_id
        / "config"
        / result["snapshot_name"]
    )
    assert snapshot.is_file()
    assert snapshot.read_text(encoding="utf-8") == "motd=Hi\n"


def test_edit_refuses_stale_revision(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    content = client.get(
        f"/api/v1/profiles/{profile_id}/files/config/content",
        params={"path": "server.properties"},
    ).json()
    (folder / "server.properties").write_text("motd=Changed\n", encoding="utf-8")
    response = client.put(
        f"/api/v1/profiles/{profile_id}/files/config/content",
        headers=headers,
        json={
            "path": "server.properties",
            "revision": content["revision"],
            "content": "motd=Bye\n",
        },
    )
    assert response.status_code == 409


def test_logs_category_is_read_only(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, headers, profile_id = api
    content = client.get(
        f"/api/v1/profiles/{profile_id}/files/logs/content", params={"path": "latest.log"}
    )
    assert content.status_code == 200
    assert content.json()["editable"] is False

    edit = client.put(
        f"/api/v1/profiles/{profile_id}/files/logs/content",
        headers=headers,
        json={"path": "latest.log", "revision": content.json()["revision"], "content": "x"},
    )
    assert edit.status_code == 409

    upload = client.post(
        f"/api/v1/profiles/{profile_id}/files/logs/upload",
        headers=headers,
        data={"path": ""},
        files=[("files", ("new.log", b"data", "text/plain"))],
    )
    assert upload.status_code == 409


def test_downloads_a_file(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, _headers, profile_id = api
    response = client.get(
        f"/api/v1/profiles/{profile_id}/files/world/download", params={"path": "world/level.dat"}
    )
    assert response.status_code == 200
    assert response.content == b"world-data"


def test_upload_refuses_existing_name(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, headers, profile_id = api
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/config/upload",
        headers=headers,
        data={"path": ""},
        files=[("files", ("server.properties", b"motd=New\n", "text/plain"))],
    )
    assert response.status_code == 409


def test_upload_writes_new_file(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/config/upload",
        headers=headers,
        data={"path": ""},
        files=[("files", ("extra.txt", b"hello", "text/plain"))],
    )
    assert response.status_code == 200
    assert response.json()["uploaded"] == ["extra.txt"]
    assert (folder / "extra.txt").read_bytes() == b"hello"


def test_renames_a_file(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/config/rename",
        headers=headers,
        json={"path": "server.properties", "new_name": "server.properties.bak"},
    )
    assert response.status_code == 200
    assert response.json()["path"] == "server.properties.bak"
    assert (folder / "server.properties.bak").is_file()
    assert not (folder / "server.properties").exists()


def test_cannot_rename_a_top_level_world_folder(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, _folder, headers, profile_id = api
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/world/rename",
        headers=headers,
        json={"path": "world", "new_name": "world2"},
    )
    assert response.status_code == 409


def test_deletes_a_file_with_snapshot(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    response = client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}/files/config",
        headers=headers,
        params={"path": "server.properties"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_name"] is not None
    assert not (folder / "server.properties").exists()


def test_deletes_a_directory_by_preserving_it(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, folder, headers, profile_id = api
    (folder / "mods" / "extra-data").mkdir()
    response = client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}/files/extensions",
        headers=headers,
        params={"path": "extra-data"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["preserved_name"] is not None
    assert (folder / "mods" / body["preserved_name"]).is_dir()
    assert not (folder / "mods" / "extra-data").exists()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_extracts_an_archive(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    archive = _zip_bytes({"datapacks/pack.txt": b"contents"})
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/world/archive/extract",
        headers=headers,
        data={"path": "world"},
        files={"file": ("pack.zip", archive, "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert "datapacks" in body["promoted"]
    assert (folder / "world" / "datapacks" / "pack.txt").read_bytes() == b"contents"


def test_extract_rejects_zip_slip(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, headers, profile_id = api
    archive = _zip_bytes({"../evil.txt": b"pwned"})
    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/world/archive/extract",
        headers=headers,
        data={"path": "world"},
        files={"file": ("evil.zip", archive, "application/zip")},
    )
    assert response.status_code == 409


def test_backups_category_is_read_only(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, _folder, headers, profile_id = api
    listing = client.get(f"/api/v1/profiles/{profile_id}/files/backups")
    assert listing.status_code == 200
    assert listing.json()["writable"] is False

    response = client.post(
        f"/api/v1/profiles/{profile_id}/files/backups/upload",
        headers=headers,
        data={"path": ""},
        files=[("files", ("x.txt", b"data", "text/plain"))],
    )
    assert response.status_code == 409
