from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.modrinth import PlannedFile


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    root = tmp_path / "servers"
    settings = Settings(
        data_dir=tmp_path / "data", server_root=root, allowed_origins="http://testserver"
    )
    with TestClient(create_app(settings)) as client:
        yield client, root


@pytest.fixture
def headers(api: tuple[TestClient, Path]) -> dict[str, str]:
    client, _ = api
    response = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


@pytest.fixture
def paper_profile(api: tuple[TestClient, Path], headers: dict[str, str]) -> str:
    client, root = api
    folder = root / "paper-server"
    folder.mkdir(parents=True)
    (folder / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    (folder / "paper.yml").write_text("", encoding="utf-8")
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Paper", "path": str(folder)}
    )
    assert created.status_code == 201
    return str(created.json()["id"])


def test_upload_toggle_and_remove_flow(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    upload = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/upload",
        headers=headers,
        files={"file": ("essentials.jar", b"jar bytes", "application/java-archive")},
    )
    assert upload.status_code == 201
    assert (root / "paper-server" / "plugins" / "essentials.jar").is_file()

    toggle = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/toggle",
        headers=headers,
        json={"file_name": "essentials.jar", "enabled": False},
    )
    assert toggle.status_code == 200
    assert (root / "paper-server" / "plugins-disabled" / "essentials.jar").is_file()

    view = client.get(f"/api/v1/profiles/{paper_profile}/extensions").json()
    assert view["entries"] == []
    assert view["disabled_entries"][0]["file_name"] == "essentials.jar"

    removed = client.delete(
        f"/api/v1/profiles/{paper_profile}/extensions/essentials.jar?disabled=true",
        headers=headers,
    )
    assert removed.status_code == 200
    assert not (root / "paper-server" / "plugins-disabled" / "essentials.jar").exists()


def test_traversal_file_names_are_refused(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, _ = api
    response = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/toggle",
        headers=headers,
        json={"file_name": "../../secrets.jar", "enabled": False},
    )
    assert response.status_code == 409
    upload = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/upload",
        headers=headers,
        files={"file": ("../evil.jar", b"jar", "application/java-archive")},
    )
    assert upload.status_code == 400


def test_install_downloads_planned_files(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    planned = [
        PlannedFile(
            project_id="proj",
            version_id="ver",
            version_number="1.0",
            file_name="thing.jar",
            url="https://cdn.example/thing.jar",
            checksum_algorithm="sha512",
            checksum="ignored",
            required_by=None,
        )
    ]

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        project_id: str,
        version_id: str | None = None,
    ) -> list[PlannedFile]:
        assert distribution == "paper"
        return planned

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        (directory / file_name).write_bytes(b"downloaded")
        return "c" * 64

    monkeypatch.setattr("blockstead.app.plan_install", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)
    response = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "proj"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["installed"][0]["file_name"] == "thing.jar"
    assert body["restart_required"] is True
    assert (root / "paper-server" / "plugins" / "thing.jar").is_file()

    again = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "proj"},
    )
    assert again.json()["skipped"] == ["thing.jar"]
