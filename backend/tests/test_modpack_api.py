from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.modpacks import ModpackError, ModpackResult


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


def make_result(root: Path, directory_name: str) -> ModpackResult:
    target = root / directory_name
    target.mkdir(parents=True)
    (target / "fabric-server-launch.jar").write_bytes(b"launcher")
    return ModpackResult(
        directory=str(target),
        name="Adventure Pack",
        minecraft_version="1.21.1",
        loader_version="0.16.5",
        installed_files=3,
        override_files=2,
        skipped_unsupported=["mods/shader.jar"],
        notes=[],
    )


def test_modpack_install_creates_fabric_profile(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api

    async def fake_fetch(
        _client: httpx.AsyncClient, project_id: str, version_id: str | None
    ) -> bytes:
        return b"mrpack bytes"

    async def fake_install(
        _client: httpx.AsyncClient, server_root: Path, directory_name: str, data: bytes
    ) -> ModpackResult:
        assert data == b"mrpack bytes"
        return make_result(server_root, directory_name)

    monkeypatch.setattr("blockstead.app.fetch_mrpack", fake_fetch)
    monkeypatch.setattr("blockstead.app.install_modpack", fake_install)
    response = client.post(
        "/api/v1/modpacks/install",
        headers=headers,
        json={
            "name": "Adventure",
            "directory_name": "adventure",
            "project_id": "pack-proj",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["minecraft_version"] == "1.21.1"
    assert body["eula_accepted"] is False
    profiles = client.get("/api/v1/profiles").json()
    assert profiles[0]["distribution"] == "fabric"
    assert profiles[0]["minecraft_version"] == "1.21.1"


def test_modpack_upload_rejects_bad_pack(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    async def failing(
        _client: httpx.AsyncClient, server_root: Path, directory_name: str, data: bytes
    ) -> ModpackResult:
        raise ModpackError("That file is not a Modrinth modpack (.mrpack).")

    monkeypatch.setattr("blockstead.app.install_modpack", failing)
    response = client.post(
        "/api/v1/modpacks/upload",
        headers=headers,
        data={"name": "Bad", "directory_name": "bad"},
        files={"file": ("bad.mrpack", b"not a zip", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "not a Modrinth modpack" in response.json()["error"]["message"]
    assert client.get("/api/v1/profiles").json() == []
