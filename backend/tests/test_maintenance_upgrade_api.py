import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.java_runtime import JavaRuntime
from blockstead.models import Profile
from blockstead.paper_builds import PaperBuild
from blockstead.provisioning import ProvisionPlan


@pytest.fixture
def upgrade_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A stopped vanilla server with three published upgrade candidates."""

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
        return ["1.21.6", "1.21.5", "1.21.4"]

    monkeypatch.setattr("blockstead.app.list_versions", fake_versions)
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
        assert created.status_code == 201, created.text
        profile_id = created.json()["id"]
        with client.app.state.session_factory() as db:
            profile = db.get(Profile, profile_id)
            assert profile is not None
            profile.minecraft_version = "1.21.4"
            db.commit()
        backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
        assert backup.status_code == 201, backup.text
        yield client, headers, profile_id, folder


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

        session_class = client.app.state.session_factory.class_
        original_commit = session_class.commit
        fail_next_commit = True

        def fail_commit_once(session: object) -> None:
            nonlocal fail_next_commit
            if fail_next_commit:
                fail_next_commit = False
                raise SQLAlchemyError("forced recovery commit failure")
            original_commit(session)

        monkeypatch.setattr(session_class, "commit", fail_commit_once)
        failed_recovery = client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/"
            f"{applied.json()['recovery_id']}",
            headers=headers,
        )
        assert failed_recovery.status_code == 500
        assert "newer launch file was put back" in failed_recovery.json()["error"]["message"]
        assert (folder / "server.jar").read_bytes() == b"new server"
        unchanged_profile = next(
            item for item in client.get("/api/v1/profiles").json() if item["id"] == profile_id
        )
        assert unchanged_profile["minecraft_version"] == "1.21.6"
        still_available = client.get(
            f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recoveries",
            headers=headers,
        )
        assert still_available.json()["recoveries"][0]["recovery_id"] == applied.json()[
            "recovery_id"
        ]

        recovered = client.post(
            f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/"
            f"{applied.json()['recovery_id']}",
            headers=headers,
        )
        assert recovered.status_code == 200, recovered.text
        assert (folder / "server.jar").read_bytes() == b"old server"
        assert recovered.json()["minecraft_version"] == "1.21.4"
        assert world.joinpath("level.dat").read_bytes() == b"world"


def test_preflight_can_select_an_older_published_upgrade_target(upgrade_environment) -> None:
    client, headers, profile_id, _folder = upgrade_environment

    older = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert older.status_code == 200, older.text
    older_plan = older.json()
    assert older_plan["upgrade_target"] == "1.21.5"
    assert "1.21.5" in next(
        item["detail"] for item in older_plan["findings"] if item["id"] == "upgrade-target"
    )

    newest = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade"},
    )
    assert newest.status_code == 200, newest.text
    assert newest.json()["upgrade_target"] == "1.21.6"
    assert newest.json()["plan_id"] != older_plan["plan_id"]


def test_upgrade_preflight_checks_java_for_the_selected_target(
    upgrade_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, headers, profile_id, _folder = upgrade_environment

    async def future_versions(
        _client: httpx.AsyncClient, distribution: str
    ) -> list[str]:
        assert distribution == "vanilla"
        return ["26.1", "1.21.4"]

    monkeypatch.setattr("blockstead.app.list_versions", future_versions)
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "26.1"},
    )

    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    compatibility = next(
        item for item in plan["findings"] if item["id"] == "compatibility"
    )
    assert plan["readiness"] == "blocked"
    assert compatibility["status"] == "blocked"
    assert "Java 25" in compatibility["detail"]


def test_apply_refuses_a_plan_reviewed_for_a_different_target(upgrade_environment) -> None:
    client, headers, profile_id, folder = upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text

    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={"minecraft_version": "1.21.6", "plan_id": reviewed.json()["plan_id"]},
    )
    assert response.status_code == 409, response.text
    assert "target changed" in response.text
    assert (folder / "server.jar").read_bytes() == b"old server"


def test_apply_installs_the_reviewed_older_target_and_keeps_recovery(
    upgrade_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, headers, profile_id, folder = upgrade_environment
    plan = ProvisionPlan(
        distribution="vanilla",
        minecraft_version="1.21.5",
        file_name="server.jar",
        url="https://example.test/server-1.21.5.jar",
        checksum_algorithm="sha1",
        checksum=hashlib.sha1(b"older server").hexdigest(),  # noqa: S324 - publisher format
        notes=["Test release"],
    )

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        version: str,
        loader_version: str | None = None,
    ) -> ProvisionPlan:
        assert (distribution, version, loader_version) == ("vanilla", "1.21.5", None)
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
        (directory / file_name).write_bytes(b"older server")
        return hashlib.sha256(b"older server").hexdigest()

    monkeypatch.setattr("blockstead.app.resolve_plan", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)

    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["minecraft_version"] == "1.21.5"
    assert (folder / "server.jar").read_bytes() == b"older server"

    recovered = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/"
        f"{applied.json()['recovery_id']}",
        headers=headers,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["minecraft_version"] == "1.21.4"
    assert (folder / "server.jar").read_bytes() == b"old server"


def test_preflight_rejects_an_unpublished_upgrade_target(upgrade_environment) -> None:
    client, headers, profile_id, _folder = upgrade_environment
    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.3"},
    )
    assert response.status_code in {409, 422}
    assert "not a currently published newer" in response.text


def test_scheduling_re_reviews_the_exact_upgrade_target(upgrade_environment) -> None:
    client, headers, profile_id, _folder = upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    run_at = "2099-01-01T10:00"

    booked = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.5",
            "plan_id": reviewed.json()["plan_id"],
            "run_at": run_at,
        },
    )
    assert booked.status_code == 201, booked.text
    assert booked.json()["minecraft_version"] == "1.21.5"

    mismatched = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.6",
            "plan_id": reviewed.json()["plan_id"],
            "run_at": "2099-01-02T10:00",
        },
    )
    assert mismatched.status_code == 409, mismatched.text
    assert mismatched.json()["error"]["code"] == "stale_plan"


@pytest.fixture
def paper_upgrade_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "servers"
    root.mkdir()
    folder = root / "paper"
    folder.mkdir()
    old_bytes = b"paper build 10"
    (folder / "server.jar").write_bytes(old_bytes)
    (folder / "paper.yml").write_text("name: Paper\n", encoding="utf-8")
    (folder / "server.properties").write_text("motd=Paper test\n", encoding="utf-8")
    world = folder / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world")

    def build(
        build_id: int, content: bytes, version: str = "1.21.4"
    ) -> PaperBuild:
        return PaperBuild(
            id=build_id,
            channel="STABLE",
            url=f"https://example.test/paper-{version}-{build_id}.jar",
            file_name=f"paper-{version}-{build_id}.jar",
            sha256=hashlib.sha256(content).hexdigest(),
        )

    builds = {
        "1.21.4": (build(10, old_bytes), build(11, b"paper build 11")),
        "1.21.5": (
            build(20, b"paper build 20", "1.21.5"),
            build(19, b"paper build 19", "1.21.5"),
        ),
    }
    contents = {
        hashlib.sha256(old_bytes).hexdigest(): old_bytes,
        hashlib.sha256(b"paper build 11").hexdigest(): b"paper build 11",
        hashlib.sha256(b"paper build 20").hexdigest(): b"paper build 20",
        hashlib.sha256(b"paper build 19").hexdigest(): b"paper build 19",
    }

    async def fake_versions(_client: httpx.AsyncClient, distribution: str) -> list[str]:
        assert distribution == "paper"
        return ["1.21.5", "1.21.4"]

    async def fake_builds(
        _client: httpx.AsyncClient, version: str
    ) -> tuple[PaperBuild, ...]:
        return builds[version]

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        version: str,
        loader_version: str | None = None,
        paper_build: int | None = None,
    ) -> ProvisionPlan:
        assert distribution == "paper"
        choices = builds[version]
        chosen = next(
            item
            for item in choices
            if item.channel == "STABLE" and (paper_build is None or item.id == paper_build)
        )
        return ProvisionPlan(
            distribution="paper",
            minecraft_version=version,
            file_name=chosen.file_name,
            url=chosen.url,
            checksum_algorithm="sha256",
            checksum=chosen.sha256,
            notes=["test Paper build"],
            paper_build=chosen.id,
        )

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        del url, checksum_algorithm
        assert checksum is not None
        content = contents[checksum]
        (directory / file_name).write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    monkeypatch.setattr("blockstead.app.list_versions", fake_versions)
    monkeypatch.setattr("blockstead.app.list_paper_builds", fake_builds)
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
            json={"name": "Paper", "path": str(folder)},
        )
        assert created.status_code == 201, created.text
        profile_id = created.json()["id"]
        with client.app.state.session_factory() as db:
            profile = db.get(Profile, profile_id)
            assert profile is not None
            profile.minecraft_version = "1.21.4"
            db.commit()
        backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
        assert backup.status_code == 201, backup.text
        yield client, headers, profile_id, folder, builds


def test_paper_same_version_build_update_pins_digest_and_recovers(
    paper_upgrade_environment,
) -> None:
    client, headers, profile_id, folder, _builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.4",
            "paper_build": 11,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["upgrade_target"] == "1.21.4"
    assert plan["upgrade_paper_build"] == 11
    assert plan["upgrade_paper_sha256"] == hashlib.sha256(b"paper build 11").hexdigest()
    reviewed_profile = next(
        item for item in client.get("/api/v1/profiles").json() if item["id"] == profile_id
    )
    assert reviewed_profile["paper_build"] == 10

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.4",
            "paper_build": 11,
            "plan_id": plan["plan_id"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["minecraft_version"] == "1.21.4"
    assert applied.json()["paper_build"] == 11
    assert (folder / "server.jar").read_bytes() == b"paper build 11"
    applied_profile = next(
        item for item in client.get("/api/v1/profiles").json() if item["id"] == profile_id
    )
    assert applied_profile["paper_build"] == 11
    available = client.get(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recoveries",
        headers=headers,
    )
    assert available.status_code == 200, available.text
    assert available.json()["recoveries"][0]["recovery_id"] == applied.json()["recovery_id"]

    recovered = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/"
        f"{applied.json()['recovery_id']}",
        headers=headers,
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["minecraft_version"] == "1.21.4"
    assert recovered.json()["paper_build"] == 10
    assert (folder / "server.jar").read_bytes() == b"paper build 10"
    recovered_profile = next(
        item for item in client.get("/api/v1/profiles").json() if item["id"] == profile_id
    )
    assert recovered_profile["paper_build"] == 10
    available_after = client.get(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/recoveries",
        headers=headers,
    )
    assert available_after.json()["recoveries"] == []


def test_paper_cross_version_preflight_honors_explicit_build_pin(
    paper_upgrade_environment,
) -> None:
    client, headers, profile_id, folder, builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.5",
            "paper_build": 19,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["upgrade_target"] == "1.21.5"
    assert plan["upgrade_paper_build"] == 19
    assert plan["upgrade_paper_sha256"] == hashlib.sha256(
        b"paper build 19"
    ).hexdigest()

    new_content = b"paper build 21"
    builds["1.21.5"] = (
        PaperBuild(
            id=21,
            channel="STABLE",
            url="https://example.test/paper-1.21.5-21.jar",
            file_name="paper-1.21.5-21.jar",
            sha256=hashlib.sha256(new_content).hexdigest(),
        ),
        *builds["1.21.5"],
    )

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "paper_build": 19,
            "plan_id": plan["plan_id"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["paper_build"] == 19
    assert (folder / "server.jar").read_bytes() == b"paper build 19"


def test_paper_schedule_rechecks_when_a_new_cross_version_build_appears(
    paper_upgrade_environment,
) -> None:
    client, headers, profile_id, _folder, builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    reviewed_plan = reviewed.json()
    assert reviewed_plan["upgrade_paper_build"] == 20

    new_content = b"paper build 21"
    builds["1.21.5"] = (
        PaperBuild(
            id=21,
            channel="STABLE",
            url="https://example.test/paper-1.21.5-21.jar",
            file_name="paper-1.21.5-21.jar",
            sha256=hashlib.sha256(new_content).hexdigest(),
        ),
        *builds["1.21.5"],
    )

    booked = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.5",
            "plan_id": reviewed_plan["plan_id"],
            "run_at": "2099-01-01T10:00",
        },
    )
    assert booked.status_code == 409, booked.text
    assert booked.json()["error"]["code"] == "stale_plan"
    assert booked.json()["plan"]["upgrade_paper_build"] == 21


def test_paper_apply_rejects_a_changed_active_jar_before_overwriting_it(
    paper_upgrade_environment,
) -> None:
    client, headers, profile_id, folder, _builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["upgrade_paper_build"] == 20
    changed = b"owner changed the active jar"
    (folder / "server.jar").write_bytes(changed)

    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "paper_build": 20,
            "plan_id": plan["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert "changed since the review" in applied.text
    assert (folder / "server.jar").read_bytes() == changed


def test_paper_preflight_blocks_when_active_jar_cannot_be_read(
    paper_upgrade_environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, headers, profile_id, _folder, _builds = paper_upgrade_environment

    def unreadable(_path: Path) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr("blockstead.app._file_sha256", unreadable)
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["readiness"] == "blocked"
    finding = next(item for item in plan["findings"] if item["id"] == "upgrade-target")
    assert finding["status"] == "blocked"
    assert "could not read the active Paper jar" in finding["detail"]
    assert "active Paper jar is readable" in finding["recommendation"]


def test_paper_same_version_preflight_rejects_unavailable_build(
    paper_upgrade_environment,
) -> None:
    client, headers, profile_id, _folder, _builds = paper_upgrade_environment
    response = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.4",
            "paper_build": 12,
        },
    )
    assert response.status_code == 409, response.text
    assert "not a published stable build for that target" in response.text


def test_paper_apply_rejects_a_wrong_stable_build_id(paper_upgrade_environment) -> None:
    client, headers, profile_id, folder, _builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.4",
            "paper_build": 11,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.4",
            "paper_build": 12,
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "server.jar").read_bytes() == b"paper build 10"


def test_paper_apply_rejects_a_changed_published_digest(paper_upgrade_environment) -> None:
    client, headers, profile_id, folder, builds = paper_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.4",
            "paper_build": 11,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    original = builds["1.21.4"][1]
    builds["1.21.4"] = (
        builds["1.21.4"][0],
        PaperBuild(
            id=original.id,
            channel=original.channel,
            url=original.url,
            file_name=original.file_name,
            sha256=hashlib.sha256(b"Paper build 11 was republished").hexdigest(),
        ),
    )
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.4",
            "paper_build": 11,
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "server.jar").read_bytes() == b"paper build 10"


@pytest.fixture
def fabric_upgrade_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "servers"
    root.mkdir()
    folder = root / "fabric"
    folder.mkdir()
    old_bytes = b"fabric launcher before"
    (folder / "fabric-server-launch.jar").write_bytes(old_bytes)
    (folder / "server.properties").write_text("motd=Fabric test\n", encoding="utf-8")
    world = folder / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world")

    def launcher_bytes(marker: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            archive.writestr("fabric-test-marker.txt", marker)
        return buffer.getvalue()

    def malformed_launcher_bytes() -> bytes:
        payload = bytearray(launcher_bytes("malformed"))
        payload[:4] = b"FAIL"
        return bytes(payload)

    loader_catalog = {
        "1.21.4": ("0.16.5", "0.16.6"),
        "1.21.5": ("0.17.0",),
    }
    artifact = {"name": "first", "invalid": False, "malformed": False}

    async def fake_versions(_client: httpx.AsyncClient, distribution: str) -> list[str]:
        assert distribution == "fabric"
        return ["1.21.5", "1.21.4"]

    async def fake_loaders(
        _client: httpx.AsyncClient, version: str
    ) -> tuple[str, ...]:
        return loader_catalog[version]

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        version: str,
        loader_version: str | None = None,
        paper_build: int | None = None,
    ) -> ProvisionPlan:
        del paper_build
        assert distribution == "fabric"
        loader = loader_version or loader_catalog[version][-1]
        return ProvisionPlan(
            distribution="fabric",
            minecraft_version=version,
            loader_version=loader,
            file_name=f"fabric-{version}-{loader}-{artifact['name']}.jar",
            url=f"https://example.test/fabric/{version}/{loader}/{artifact['name']}",
            checksum_algorithm=None,
            checksum=None,
            notes=["test Fabric launcher"],
        )

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        del url, checksum_algorithm, checksum
        if artifact["invalid"]:
            content = b"<html>temporary upstream error</html>"
        elif artifact["malformed"]:
            content = malformed_launcher_bytes()
        else:
            content = launcher_bytes(str(artifact["name"]))
        (directory / file_name).write_bytes(content)
        return hashlib.sha256(content).hexdigest()

    monkeypatch.setattr("blockstead.app.list_versions", fake_versions)
    monkeypatch.setattr("blockstead.app.list_fabric_stable_loaders", fake_loaders)
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
            json={"name": "Fabric", "path": str(folder)},
        )
        assert created.status_code == 201, created.text
        profile_id = created.json()["id"]
        with client.app.state.session_factory() as db:
            profile = db.get(Profile, profile_id)
            assert profile is not None
            profile.minecraft_version = "1.21.4"
            db.commit()
        backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
        assert backup.status_code == 201, backup.text
        yield client, headers, profile_id, folder, artifact


def test_fabric_cross_version_preflight_pins_loader_and_schedule_carries_it(
    fabric_upgrade_environment,
) -> None:
    client, headers, profile_id, _folder, _artifact = fabric_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["upgrade_target"] == "1.21.5"
    assert plan["upgrade_loader_version"] == "0.17.0"
    assert plan["upgrade_loader_artifact"]

    booked = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/schedule",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.5",
            "loader_version": "0.17.0",
            "plan_id": plan["plan_id"],
            "run_at": "2099-01-01T10:00",
        },
    )
    assert booked.status_code == 201, booked.text
    assert booked.json()["loader_version"] == "0.17.0"


def test_fabric_same_version_upgrade_requires_and_records_exact_loader(
    fabric_upgrade_environment,
) -> None:
    client, headers, profile_id, folder, _artifact = fabric_upgrade_environment
    with client.app.state.session_factory() as db:
        profile = db.get(Profile, profile_id)
        assert profile is not None
        profile.loader_version = "0.16.5"
        db.commit()

    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={
            "change_id": "server_upgrade",
            "minecraft_version": "1.21.4",
            "loader_version": "0.16.6",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    plan = reviewed.json()
    assert plan["upgrade_loader_version"] == "0.16.6"
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.4",
            "loader_version": "0.16.6",
            "plan_id": plan["plan_id"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["loader_version"] == "0.16.6"
    assert zipfile.is_zipfile(folder / "fabric-server-launch.jar")


def test_fabric_apply_rejects_a_changed_active_launcher(fabric_upgrade_environment) -> None:
    client, headers, profile_id, folder, _artifact = fabric_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    changed = b"owner changed the Fabric launcher"
    (folder / "fabric-server-launch.jar").write_bytes(changed)
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "loader_version": "0.17.0",
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "fabric-server-launch.jar").read_bytes() == changed


def test_fabric_apply_rejects_launcher_artifact_drift(fabric_upgrade_environment) -> None:
    client, headers, profile_id, folder, artifact = fabric_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    artifact["name"] = "second"
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "loader_version": "0.17.0",
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "fabric-server-launch.jar").read_bytes() == b"fabric launcher before"


def test_fabric_apply_rejects_an_invalid_launcher_payload(fabric_upgrade_environment) -> None:
    client, headers, profile_id, folder, artifact = fabric_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    artifact["invalid"] = True
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "loader_version": "0.17.0",
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "fabric-server-launch.jar").read_bytes() == b"fabric launcher before"


def test_fabric_apply_rejects_a_malformed_launcher_archive(fabric_upgrade_environment) -> None:
    client, headers, profile_id, folder, artifact = fabric_upgrade_environment
    reviewed = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/preflight",
        headers=headers,
        json={"change_id": "server_upgrade", "minecraft_version": "1.21.5"},
    )
    assert reviewed.status_code == 200, reviewed.text
    artifact["malformed"] = True
    applied = client.post(
        f"/api/v1/profiles/{profile_id}/maintenance/upgrades/apply",
        headers=headers,
        json={
            "minecraft_version": "1.21.5",
            "loader_version": "0.17.0",
            "plan_id": reviewed.json()["plan_id"],
        },
    )
    assert applied.status_code == 409, applied.text
    assert (folder / "fabric-server-launch.jar").read_bytes() == b"fabric launcher before"
