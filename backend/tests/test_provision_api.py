from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.provisioning import ProvisionError, ProvisionPlan, ProvisionResult


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


def make_result(
    directory: Path,
    *,
    distribution: str = "vanilla",
    paper_build: int | None = None,
) -> ProvisionResult:
    plan = ProvisionPlan(
        distribution=distribution,
        minecraft_version="1.21.1",
        file_name="server.jar",
        url="https://example.invalid/server.jar",
        checksum_algorithm="sha256" if distribution == "paper" else "sha1",
        checksum="a" * (64 if distribution == "paper" else 40),
        notes=["test note"],
        paper_build=paper_build,
    )
    directory.mkdir(parents=True)
    (directory / "server.jar").write_bytes(b"jar")
    return ProvisionResult(plan=plan, directory=str(directory), sha256="b" * 64)


def test_provision_creates_profile(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api

    async def fake_provision(
        _client: httpx.AsyncClient,
        server_root: Path,
        name: str,
        dist: str,
        version: str,
        loader_version: str | None,
        java_executable: str | None,
    ) -> ProvisionResult:
        return make_result(server_root / name)

    monkeypatch.setattr("blockstead.app.provision_profile", fake_provision)
    response = client.post(
        "/api/v1/provision",
        headers=headers,
        json={
            "name": "Family Server",
            "directory_name": "family-server",
            "distribution": "vanilla",
            "minecraft_version": "1.21.1",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["eula_accepted"] is False
    assert body["sha256"] == "b" * 64
    profiles = client.get("/api/v1/profiles").json()
    assert profiles[0]["distribution"] == "vanilla"
    assert profiles[0]["minecraft_version"] == "1.21.1"
    assert profiles[0]["paper_build"] is None


def test_paper_provision_records_the_exact_build_for_server_info(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api

    async def fake_provision(
        _client: httpx.AsyncClient,
        server_root: Path,
        name: str,
        dist: str,
        version: str,
        loader_version: str | None,
        java_executable: str | None,
    ) -> ProvisionResult:
        assert (dist, version) == ("paper", "1.21.1")
        return make_result(
            server_root / name,
            distribution="paper",
            paper_build=205,
        )

    monkeypatch.setattr("blockstead.app.provision_profile", fake_provision)
    response = client.post(
        "/api/v1/provision",
        headers=headers,
        json={
            "name": "Paper Family",
            "directory_name": "paper-family",
            "distribution": "paper",
            "minecraft_version": "1.21.1",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["paper_build"] == 205
    profile = client.get("/api/v1/profiles").json()[0]
    assert profile["minecraft_version"] == "1.21.1"
    assert profile["paper_build"] == 205


def test_provision_error_is_a_safe_400(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    async def failing(
        _client: httpx.AsyncClient,
        server_root: Path,
        name: str,
        dist: str,
        version: str,
        loader_version: str | None,
        java_executable: str | None,
    ) -> ProvisionResult:
        raise ProvisionError("A download source did not answer as expected (Timeout).")

    monkeypatch.setattr("blockstead.app.provision_profile", failing)
    response = client.post(
        "/api/v1/provision",
        headers=headers,
        json={
            "name": "Broken",
            "directory_name": "broken",
            "distribution": "paper",
            "minecraft_version": "1.21.1",
        },
    )
    assert response.status_code == 400
    assert "download source" in response.json()["error"]["message"]
    assert client.get("/api/v1/profiles").json() == []


def test_eula_acceptance_is_explicit(api: tuple[TestClient, Path], headers: dict[str, str]) -> None:
    client, root = api
    folder = root / "manual-server"
    folder.mkdir(parents=True)
    (folder / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    (folder / "server.jar").write_bytes(b"jar")
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Manual", "path": str(folder)}
    )
    assert created.status_code == 201
    profile_id = created.json()["id"]

    refused = client.post(
        f"/api/v1/profiles/{profile_id}/eula", headers=headers, json={"accept": False}
    )
    assert refused.status_code == 422
    assert not (folder / "eula.txt").exists()

    accepted = client.post(
        f"/api/v1/profiles/{profile_id}/eula", headers=headers, json={"accept": True}
    )
    assert accepted.status_code == 200
    assert "eula=true" in (folder / "eula.txt").read_text(encoding="utf-8")
    prerequisites = client.get(f"/api/v1/profiles/{profile_id}/prerequisites").json()
    assert prerequisites["eula_accepted"] is True


def test_provision_rejects_invalid_directory_name_with_field_error(
    api: tuple[TestClient, Path], headers: dict[str, str]
) -> None:
    from blockstead.validation import DIRECTORY_PATTERN

    client, _ = api
    response = client.post(
        "/api/v1/provision",
        headers=headers,
        json={
            "name": "My Server",
            "directory_name": "My Server!",
            "distribution": "vanilla",
            "minecraft_version": "1.21.1",
        },
    )
    assert response.status_code == 422
    body = response.json()
    fields = body["error"]["fields"]
    assert fields
    assert fields[0]["field"] == "directory_name"
    assert fields[0]["reason"]
    assert fields[0]["rule"]
    assert DIRECTORY_PATTERN.match(fields[0]["suggestion"])


def test_provision_directory_already_exists_returns_field_error(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    (root / "family-server").mkdir(parents=True)

    async def already_exists(
        _client: httpx.AsyncClient,
        server_root: Path,
        name: str,
        dist: str,
        version: str,
        loader_version: str | None,
        java_executable: str | None,
    ) -> ProvisionResult:
        raise ProvisionError("A folder with that name already exists in the server root.")

    monkeypatch.setattr("blockstead.app.provision_profile", already_exists)
    response = client.post(
        "/api/v1/provision",
        headers=headers,
        json={
            "name": "Family Server",
            "directory_name": "family-server",
            "distribution": "vanilla",
            "minecraft_version": "1.21.1",
        },
    )
    assert response.status_code == 409
    field_error = response.json()["error"]["fields"][0]
    assert field_error["field"] == "directory_name"
    assert field_error["reason"] == "ALREADY_EXISTS"
    assert field_error["suggestion"] == "family-server-2"
