import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.java_runtime import JavaRuntime
from blockstead.models import Profile
from blockstead.provisioning import ProvisionPlan


def test_reviewed_server_upgrade_preserves_and_restores_the_launch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers"
    root.mkdir()
    folder = root / "vanilla"
    folder.mkdir()
    (folder / "server.jar").write_bytes(b"old server")
    (folder / "server.properties").write_text("motd=Upgrade test\n", encoding="utf-8")
    world = folder / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world")

    async def fake_versions(_client: httpx.AsyncClient, distribution: str) -> list[str]:
        assert distribution == "vanilla"
        return ["1.21.6", "1.21.4"]

    plan = ProvisionPlan(
        distribution="vanilla",
        minecraft_version="1.21.6",
        file_name="server.jar",
        url="https://example.test/server.jar",
        checksum_algorithm="sha1",
        checksum=hashlib.sha1(b"new server").hexdigest(),  # noqa: S324 - publisher format
        notes=["Test release"],
    )

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        version: str,
        loader_version: str | None = None,
    ) -> ProvisionPlan:
        assert (distribution, version, loader_version) == ("vanilla", "1.21.6", None)
        return plan

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        assert (url, file_name, checksum_algorithm, checksum) == (
            plan.url,
            "server.jar",
            "sha1",
            plan.checksum,
        )
        (directory / file_name).write_bytes(b"new server")
        return hashlib.sha256(b"new server").hexdigest()

    monkeypatch.setattr("blockstead.app.list_versions", fake_versions)
    monkeypatch.setattr("blockstead.app.resolve_plan", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)
    monkeypatch.setattr(
        "blockstead.app.discover_java_runtimes",
        lambda: [JavaRuntime(path="/test/java", version="21", major=21)],
    )

    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=root,
        allowed_origins="http://testserver",
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
        created = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Vanilla", "path": str(folder)},
        )
        assert created.status_code == 201
        profile_id = created.json()["id"]
        with client.app.state.session_factory() as db:
            profile = db.get(Profile, profile_id)
            assert profile is not None
            profile.minecraft_version = "1.21.4"
            db.commit()

        backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
        assert backup.status_code == 201
        reviewed = client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/preflight",
            headers=headers,
            json={"change_id": "server_upgrade"},
        )
        assert reviewed.status_code == 200
        reviewed_plan = reviewed.json()
        assert reviewed_plan["readiness"] == "ready"
        assert reviewed_plan["protection"]["verified"] is True

        applied = client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
            headers=headers,
            json={
                "minecraft_version": "1.21.6",
                "plan_id": reviewed_plan["plan_id"],
            },
        )
        assert applied.status_code == 200, applied.text
        assert (folder / "server.jar").read_bytes() == b"new server"
        assert applied.json()["minecraft_version"] == "1.21.6"
        assert "never rolls a world back" in applied.json()["detail"]

        recovered = client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/"
            f"{applied.json()['recovery_id']}",
            headers=headers,
        )
        assert recovered.status_code == 200, recovered.text
        assert (folder / "server.jar").read_bytes() == b"old server"
        assert recovered.json()["minecraft_version"] == "1.21.4"
        assert world.joinpath("level.dat").read_bytes() == b"world"
