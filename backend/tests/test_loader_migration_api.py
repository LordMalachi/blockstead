from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.provisioning import ProvisionPlan, ProvisionResult

SOURCES = ("vanilla", "paper", "fabric", "forge", "quilt", "neoforge")
TARGETS = ("paper", "fabric", "forge", "quilt", "neoforge")


def source_folder(root: Path, name: str, distribution: str) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "server.properties").write_text("level-name=world\n", encoding="utf-8")
    (folder / "fake-server.json").write_text(
        '{"minecraft_version":"1.21.1"}\n', encoding="utf-8"
    )
    if distribution == "paper":
        (folder / "paper.yml").write_text("", encoding="utf-8")
        (folder / "plugins").mkdir()
        (folder / "plugins" / "source-only.jar").write_bytes(b"plugin")
        (folder / "world").mkdir()
        (folder / "world" / "owner-build.dat").write_bytes(b"overworld")
        (folder / "world_nether" / "DIM-1").mkdir(parents=True)
        (folder / "world_nether" / "DIM-1" / "level.dat").write_bytes(b"nether")
        (folder / "world_the_end" / "DIM1").mkdir(parents=True)
        (folder / "world_the_end" / "DIM1" / "level.dat").write_bytes(b"end")
    else:
        marker = {
            "vanilla": "server.jar",
            "fabric": "fabric-server-launch.jar",
            "forge": "forge-test.jar",
            "quilt": "quilt-server-launch.jar",
            "neoforge": "neoforge-test.jar",
        }[distribution]
        (folder / marker).write_bytes(b"launcher")
        if distribution != "vanilla":
            (folder / "mods").mkdir()
            (folder / "mods" / "source-only.jar").write_bytes(b"mod")
        (folder / "world" / "DIM-1").mkdir(parents=True)
        (folder / "world" / "DIM1").mkdir(parents=True)
        (folder / "world" / "owner-build.dat").write_bytes(b"overworld")
        (folder / "world" / "DIM-1" / "level.dat").write_bytes(b"nether")
        (folder / "world" / "DIM1" / "level.dat").write_bytes(b"end")
    (folder / "config").mkdir()
    (folder / "config" / "source-only.conf").write_text("do-not-copy=true\n")
    return folder


def plan(distribution: str) -> ProvisionPlan:
    return ProvisionPlan(
        distribution=distribution,
        minecraft_version="1.21.1",
        loader_version=None if distribution == "paper" else "test-loader",
        file_name=f"{distribution}-server.jar",
        url=f"https://example.test/{distribution}.jar",
        checksum_algorithm="sha256",
        checksum="a" * 64,
        notes=[],
    )


@pytest.fixture
def migration_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path, dict[str, str]]]:
    root = tmp_path / "servers"
    root.mkdir()
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=root,
        allowed_origins="http://testserver",
    )

    async def fake_resolve(
        _client: httpx.AsyncClient,
        distribution: str,
        version: str,
        loader_version: str | None = None,
    ) -> ProvisionPlan:
        del version, loader_version
        return plan(distribution)

    async def fake_provision(
        _client: httpx.AsyncClient,
        server_root: Path,
        directory_name: str,
        distribution: str,
        version: str,
        loader_version: str | None = None,
        java_executable: str | None = None,
    ) -> ProvisionResult:
        del version, java_executable
        target = server_root / directory_name
        target.mkdir()
        selected = plan(distribution).model_copy(update={"loader_version": loader_version})
        (target / selected.file_name).write_bytes(b"verified launcher")
        return ProvisionResult(
            plan=selected,
            directory=str(target),
            sha256="b" * 64,
        )

    monkeypatch.setattr("blockstead.app.resolve_plan", fake_resolve)
    monkeypatch.setattr("blockstead.app.provision_profile", fake_provision)
    monkeypatch.setattr("blockstead.app.required_java_major", lambda _version: None)
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
        yield client, root, headers


def create_source(
    client: TestClient,
    root: Path,
    headers: dict[str, str],
    *,
    name: str,
    distribution: str,
) -> tuple[str, str]:
    folder = source_folder(root, name, distribution)
    created = client.post(
        "/api/v1/profiles",
        headers=headers,
        json={"name": name, "path": str(folder)},
    )
    assert created.status_code == 201, created.text
    profile_id = str(created.json()["id"])
    backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
    assert backup.status_code == 201, backup.text
    return profile_id, str(backup.json()["id"])


def test_every_recognized_source_to_target_loader_combination(
    migration_api: tuple[TestClient, Path, dict[str, str]],
) -> None:
    client, root, headers = migration_api
    for source in SOURCES:
        for target in TARGETS:
            slug = f"{source}-to-{target}"
            profile_id, backup_id = create_source(
                client,
                root,
                headers,
                name=f"source-{slug}",
                distribution=source,
            )
            reviewed = client.post(
                f"/api/v1/profiles/{profile_id}/loader-migration/review",
                headers=headers,
                json={"target_distribution": target},
            )
            assert reviewed.status_code == 200, reviewed.text
            review = reviewed.json()
            assert review["ready"] is True, review["blockers"]
            applied = client.post(
                f"/api/v1/profiles/{profile_id}/loader-migration/apply",
                headers=headers,
                json={
                    "target_distribution": target,
                    "review_id": review["review_id"],
                    "backup_id": backup_id,
                    "name": f"Target {slug}",
                    "directory_name": f"target-{slug}",
                    "loader_version": review["loader_version"],
                    "acknowledge_modded_world": review["modded_world_warning"],
                },
            )
            assert applied.status_code == 201, applied.text
            source_folder_path = root / f"source-{slug}"
            target_folder = root / f"target-{slug}"
            assert (source_folder_path / "world" / "owner-build.dat").read_bytes() == b"overworld"
            assert (target_folder / "world" / "owner-build.dat").read_bytes() == b"overworld"
            if target == "paper":
                assert (target_folder / "world_nether" / "DIM-1" / "level.dat").is_file()
            else:
                assert (target_folder / "world" / "DIM-1" / "level.dat").is_file()
            assert not (target_folder / "config" / "source-only.conf").exists()
            assert not (target_folder / "mods" / "source-only.jar").exists()
            assert not (target_folder / "plugins" / "source-only.jar").exists()


def test_failed_world_copy_removes_partial_target_and_keeps_source(
    migration_api: tuple[TestClient, Path, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root, headers = migration_api
    profile_id, backup_id = create_source(
        client,
        root,
        headers,
        name="copy-failure-source",
        distribution="vanilla",
    )
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/loader-migration/review",
        headers=headers,
        json={"target_distribution": "fabric"},
    ).json()

    def fail_copy(
        _roots: object,
        target: Path,
        _level_name: str,
        _source_distribution: str,
        _target_distribution: str,
    ) -> list[str]:
        (target / "partial-world").mkdir()
        raise OSError("simulated copy failure")

    monkeypatch.setattr("blockstead.app.copy_worlds", fail_copy)
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/loader-migration/apply",
        headers=headers,
        json={
            "target_distribution": "fabric",
            "review_id": reviewed["review_id"],
            "backup_id": backup_id,
            "name": "Failed target",
            "directory_name": "failed-target",
            "loader_version": reviewed["loader_version"],
            "acknowledge_modded_world": False,
        },
    )

    assert applied.status_code == 409
    assert not (root / "failed-target").exists()
    assert (root / "copy-failure-source" / "world" / "owner-build.dat").read_bytes() == b"overworld"
    profiles = client.get("/api/v1/profiles", headers=headers).json()
    assert not any(item["name"] == "Failed target" for item in profiles)


def test_migration_discovers_a_live_world_after_stale_properties(
    migration_api: tuple[TestClient, Path, dict[str, str]],
) -> None:
    client, root, headers = migration_api
    folder = source_folder(root, "stale-properties", "vanilla")
    (folder / "world").rename(folder / "friends-world")
    (folder / "server.properties").write_text("motd=Old server\n", encoding="utf-8")
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Friends", "path": str(folder)}
    )
    assert created.status_code == 201, created.text
    profile_id = str(created.json()["id"])
    backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
    assert backup.status_code == 201, backup.text

    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/loader-migration/review",
        headers=headers,
        json={"target_distribution": "paper"},
    )
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()
    assert review["ready"] is True, review["blockers"]
    assert review["level_name"] == "friends-world"
    assert review["worlds"] == ["friends-world"]

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/loader-migration/apply",
        headers=headers,
        json={
            "target_distribution": "paper",
            "review_id": review["review_id"],
            "backup_id": backup.json()["id"],
            "name": "Friends Paper",
            "directory_name": "friends-paper",
            "loader_version": review["loader_version"],
            "acknowledge_modded_world": False,
        },
    )
    assert applied.status_code == 201, applied.text
    copied_world = root / "friends-paper" / "friends-world" / "owner-build.dat"
    assert copied_world.read_bytes() == b"overworld"
