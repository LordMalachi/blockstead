import hashlib
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.db import create_session_factory
from blockstead.extension_origins import (
    load_origin_map,
    record_catalog_files,
    record_local_files,
)
from blockstead.models import AuditEvent, Profile
from blockstead.modrinth import PlannedFile, ProjectVersion, SearchPage


def jar_bytes() -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    return content.getvalue()


def paper_plugin_bytes(name: str, dependencies: tuple[str, ...] = ()) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        depend = f"depend: [{', '.join(dependencies)}]\n" if dependencies else ""
        archive.writestr(
            "plugin.yml",
            f"name: {name}\nversion: 1.0\napi-version: '1.21'\n{depend}",
        )
    return content.getvalue()


def fabric_mod_bytes(identifier: str, environment: str = "*") -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "fabric.mod.json",
            (
                '{"schemaVersion":1,"id":"'
                + identifier
                + '","version":"1.0.0","environment":"'
                + environment
                + '"}'
            ),
        )
    return content.getvalue()


def fabric_mod_with_dependency_bytes(
    identifier: str, version: str, dependency_id: str, dependency_constraint: str
) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr(
            "fabric.mod.json",
            (
                '{"schemaVersion":1,"id":"'
                + identifier
                + '","version":"'
                + version
                + '","environment":"*","depends":{"'
                + dependency_id
                + '":"'
                + dependency_constraint
                + '"}}'
            ),
        )
    return content.getvalue()


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
    (folder / "fake-server.json").write_text('{"minecraft_version":"1.21.1"}\n', encoding="utf-8")
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Paper", "path": str(folder)}
    )
    assert created.status_code == 201
    return str(created.json()["id"])


@pytest.fixture
def fabric_profile(api: tuple[TestClient, Path], headers: dict[str, str]) -> str:
    client, root = api
    folder = root / "fabric-server"
    folder.mkdir(parents=True)
    (folder / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    (folder / "fabric-server-launch.jar").write_bytes(b"")
    (folder / "fake-server.json").write_text(
        '{"minecraft_version":"1.21.1"}\n', encoding="utf-8"
    )
    created = client.post(
        "/api/v1/profiles", headers=headers, json={"name": "Fabric", "path": str(folder)}
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
        files={"file": ("essentials.jar", jar_bytes(), "application/java-archive")},
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


def test_commands_follow_active_extension_metadata(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    before = client.get(f"/api/v1/profiles/{paper_profile}/commands")
    assert before.status_code == 200
    assert "essentialsx_spawn" not in {item["id"] for item in before.json()["commands"]}

    plugins = root / "paper-server" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (plugins / "essentials.jar").write_bytes(paper_plugin_bytes("EssentialsX"))
    active = client.get(f"/api/v1/profiles/{paper_profile}/commands").json()
    assert "essentialsx_spawn" in {item["id"] for item in active["commands"]}

    toggle = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/toggle",
        headers=headers,
        json={"file_name": "essentials.jar", "enabled": False},
    )
    assert toggle.status_code == 200
    disabled = client.get(f"/api/v1/profiles/{paper_profile}/commands").json()
    assert "essentialsx_spawn" not in {item["id"] for item in disabled["commands"]}


def test_manual_import_reviews_dependencies_then_promotes_the_batch(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    review = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/review",
        headers=headers,
        files=[
            (
                "files",
                ("base.jar", paper_plugin_bytes("Base"), "application/java-archive"),
            ),
            (
                "files",
                (
                    "addon.jar",
                    paper_plugin_bytes("Addon", ("Base",)),
                    "application/java-archive",
                ),
            ),
        ],
    )
    assert review.status_code == 201, review.text
    body = review.json()
    assert body["destination"] == "plugins"
    assert body["blockers"] == []
    assert body["requires_acknowledgement"] is False
    assert {entry["identifier"] for entry in body["files"]} == {"Base", "Addon"}

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": body["review_id"], "acknowledge_unknown": False},
    )
    assert applied.status_code == 201, applied.text
    assert applied.json()["batch_id"] == body["review_id"]
    plugins = root / "paper-server" / "plugins"
    assert (plugins / "base.jar").is_file()
    assert (plugins / "addon.jar").is_file()
    assert not list(plugins.glob(".blockstead-manual-*"))

    server = root / "paper-server"
    (server / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    world = server / "world"
    world.mkdir()
    (world / "owner-build.dat").write_bytes(b"unchanged")
    tested = client.post(
        f"/api/v1/profiles/{paper_profile}/loadout/test-start",
        headers=headers,
        json={"recent_batch_ids": [body["review_id"]], "retry_of": None},
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["status"] == "passed"
    assert tested.json()["live_world_untouched"] is True
    assert tested.json()["validation_workspace_removed"] is True
    assert (world / "owner-build.dat").read_bytes() == b"unchanged"
    assert not list(root.glob(".paper-server.blockstead-validation-*"))

    lockfile = client.get(
        f"/api/v1/profiles/{paper_profile}/loadout/lockfile",
        headers=headers,
    )
    assert lockfile.status_code == 200
    locked = lockfile.json()
    assert {item["file_name"] for item in locked["installed"]} == {
        "base.jar",
        "addon.jar",
    }
    assert {item["origin"]["source"] for item in locked["installed"]} == {"local"}
    assert not any(item["origin"]["verified"] for item in locked["installed"])

    compared = client.post(
        f"/api/v1/profiles/{paper_profile}/loadout/lockfile/review",
        headers=headers,
        files={"file": ("loadout.json", lockfile.content, "application/json")},
    )
    assert compared.status_code == 200
    assert compared.json()["compatible"] is True
    assert compared.json()["mutation_performed"] is False

    player_pack = client.get(
        f"/api/v1/profiles/{paper_profile}/loadout/player-pack",
        headers=headers,
    )
    assert player_pack.status_code == 409
    assert "Paper plugins" in player_pack.json()["error"]["message"]


def test_manual_import_blocks_an_unsatisfied_dependency_version(
    api: tuple[TestClient, Path], headers: dict[str, str], fabric_profile: str
) -> None:
    client, root = api
    # fabric-api 1.0.0 (fabric_mod_bytes's fixed version) is installed.
    upload = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/upload",
        headers=headers,
        files={
            "file": (
                "fabric-api.jar",
                fabric_mod_bytes("fabric-api"),
                "application/java-archive",
            )
        },
    )
    assert upload.status_code == 201

    review = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/manual-import/review",
        headers=headers,
        files=[
            (
                "files",
                (
                    "cool-tech.jar",
                    fabric_mod_with_dependency_bytes(
                        "cool-tech", "2.0.0", "fabric-api", ">=2.0.0"
                    ),
                    "application/java-archive",
                ),
            ),
        ],
    )
    assert review.status_code == 201, review.text
    body = review.json()
    assert body["missing_dependencies"] == []
    assert len(body["dependency_version_mismatches"]) == 1
    assert "fabric-api" in body["dependency_version_mismatches"][0]
    assert any(
        "dependency versions do not satisfy" in blocker for blocker in body["blockers"]
    )

    applied = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": body["review_id"], "acknowledge_unknown": False},
    )
    assert applied.status_code == 409
    assert "dependency versions do not satisfy" in applied.json()["error"]["message"]
    assert not (root / "fabric-server" / "mods" / "cool-tech.jar").exists()


def test_manual_import_allows_a_satisfied_dependency_version(
    api: tuple[TestClient, Path], headers: dict[str, str], fabric_profile: str
) -> None:
    client, root = api
    upload = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/upload",
        headers=headers,
        files={
            "file": (
                "fabric-api.jar",
                fabric_mod_bytes("fabric-api"),
                "application/java-archive",
            )
        },
    )
    assert upload.status_code == 201

    review = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/manual-import/review",
        headers=headers,
        files=[
            (
                "files",
                (
                    "cool-tech.jar",
                    fabric_mod_with_dependency_bytes(
                        "cool-tech", "2.0.0", "fabric-api", ">=0.5.0"
                    ),
                    "application/java-archive",
                ),
            ),
        ],
    )
    assert review.status_code == 201, review.text
    body = review.json()
    assert body["dependency_version_mismatches"] == []
    assert body["blockers"] == []

    applied = client.post(
        f"/api/v1/profiles/{fabric_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": body["review_id"], "acknowledge_unknown": False},
    )
    assert applied.status_code == 201, applied.text
    assert (root / "fabric-server" / "mods" / "cool-tech.jar").is_file()


def test_manual_import_requires_acknowledgement_for_unidentified_jars(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    review = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/review",
        headers=headers,
        files=[("files", ("mystery.jar", jar_bytes(), "application/java-archive"))],
    )
    assert review.status_code == 201
    body = review.json()
    assert body["requires_acknowledgement"] is True

    refused = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": body["review_id"], "acknowledge_unknown": False},
    )
    assert refused.status_code == 422
    assert not (root / "paper-server" / "plugins" / "mystery.jar").exists()

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": body["review_id"], "acknowledge_unknown": True},
    )
    assert applied.status_code == 201
    assert (root / "paper-server" / "plugins" / "mystery.jar").is_file()


def test_manual_import_moves_and_registers_uppercase_jar_names(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    review = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/review",
        headers=headers,
        files=[
            (
                "files",
                ("Uppercase.JAR", paper_plugin_bytes("Uppercase"), "application/java-archive"),
            )
        ],
    )
    assert review.status_code == 201, review.text

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": review.json()["review_id"], "acknowledge_unknown": False},
    )
    assert applied.status_code == 201, applied.text
    assert (root / "paper-server" / "plugins" / "Uppercase.JAR").is_file()
    inventory = client.get(f"/api/v1/profiles/{paper_profile}/extensions")
    assert inventory.status_code == 200
    assert inventory.json()["entries"][0]["file_name"] == "Uppercase.JAR"
    assert applied.json()["source_verified"] is False


@pytest.mark.parametrize("mutation", ["delete", "truncate", "replace"])
def test_manual_import_rejects_changed_staged_jars(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    mutation: str,
) -> None:
    client, root = api
    review = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/review",
        headers=headers,
        files=[
            (
                "files",
                ("reviewed.jar", paper_plugin_bytes("Reviewed"), "application/java-archive"),
            )
        ],
    )
    assert review.status_code == 201, review.text
    review_id = review.json()["review_id"]
    staging = root / "paper-server" / "plugins" / f".blockstead-manual-{review_id}"
    staged_jar = staging / "reviewed.jar"
    if mutation == "delete":
        staged_jar.unlink()
    elif mutation == "truncate":
        staged_jar.write_bytes(b"")
    else:
        staged_jar.write_bytes(paper_plugin_bytes("Replacement"))

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/manual-import/apply",
        headers=headers,
        json={"review_id": review_id, "acknowledge_unknown": False},
    )

    assert applied.status_code == 409
    assert applied.json()["error"]["message"] == (
        "A staged jar changed after review. Choose the files again."
    )
    assert not (root / "paper-server" / "plugins" / "reviewed.jar").exists()
    assert not staging.exists()
    factory = create_session_factory(root.parent / "data" / "blockstead.db")
    with factory() as db:
        successful_uploads = db.query(AuditEvent).filter_by(
            profile_id=paper_profile,
            category="extension_upload",
            result="success",
        )
        assert successful_uploads.count() == 0


def test_player_pack_download_requires_a_fresh_review(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    factory = create_session_factory(root.parent / "data" / "blockstead.db")
    with factory() as db:
        profile = db.get(Profile, paper_profile)
        assert profile is not None
        profile.distribution = "fabric"
        profile.loader_version = "0.16.10"
        db.commit()
    mods = root / "paper-server" / "mods"
    mods.mkdir()
    content = fabric_mod_bytes("client_mod", "client")
    path = mods / "client-mod.jar"
    path.write_bytes(content)
    planned = PlannedFile(
        project_id="client-project",
        version_id="client-version",
        version_number="1.0.0",
        file_name=path.name,
        url="https://cdn.modrinth.com/client-mod.jar",
        checksum_algorithm="sha512",
        checksum=hashlib.sha512(content).hexdigest(),
        required_by=None,
    )
    record_catalog_files(mods, "modrinth", [planned])

    reviewed = client.get(
        f"/api/v1/profiles/{paper_profile}/loadout/player-pack/review",
        headers=headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()
    assert review["included"][0]["file_name"] == path.name
    assert review["manual_requirements"] == []

    downloaded = client.get(
        f"/api/v1/profiles/{paper_profile}/loadout/player-pack?review_id={review['review_id']}",
        headers=headers,
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("application/x-modrinth-modpack")

    path.write_bytes(fabric_mod_bytes("client_mod", "*"))
    stale = client.get(
        f"/api/v1/profiles/{paper_profile}/loadout/player-pack?review_id={review['review_id']}",
        headers=headers,
    )
    assert stale.status_code == 409
    assert "changed after" in stale.json()["error"]["message"]


def test_toggle_all_round_trip(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    plugins = root / "paper-server" / "plugins"
    plugins.mkdir()
    (plugins / "one.jar").write_bytes(b"jar")
    (plugins / "two.jar").write_bytes(b"jar")

    disabled = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/toggle-all",
        headers=headers,
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["moved"] == ["one.jar", "two.jar"]
    assert disabled.json()["restart_required"] is True
    view = client.get(f"/api/v1/profiles/{paper_profile}/extensions").json()
    assert view["entries"] == []
    assert [entry["file_name"] for entry in view["disabled_entries"]] == ["one.jar", "two.jar"]

    restored = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/toggle-all",
        headers=headers,
        json={"enabled": True},
    )
    assert restored.status_code == 200
    assert restored.json()["moved"] == ["one.jar", "two.jar"]
    view = client.get(f"/api/v1/profiles/{paper_profile}/extensions").json()
    assert [entry["file_name"] for entry in view["entries"]] == ["one.jar", "two.jar"]
    assert view["disabled_entries"] == []


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


def test_search_passes_filters_and_reports_paging(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    captured: dict[str, object] = {}

    async def fake_search(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        query: str,
        categories: list[str] | None = None,
        sort: str = "relevance",
        offset: int = 0,
    ) -> SearchPage:
        captured.update(
            distribution=distribution, query=query, categories=categories, sort=sort, offset=offset
        )
        return SearchPage(projects=[], total=42, offset=offset, limit=20)

    monkeypatch.setattr("blockstead.app.modrinth_search", fake_search)
    response = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/search"
        "?query=perms&categories=economy,chat&sort=downloads&offset=20",
        headers=headers,
    )
    assert response.status_code == 200
    assert captured == {
        "distribution": "paper",
        "query": "perms",
        "categories": ["economy", "chat"],
        "sort": "downloads",
        "offset": 20,
    }
    body = response.json()
    assert body["total"] == 42 and body["offset"] == 20 and body["limit"] == 20


def test_categories_and_versions_endpoints(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api

    async def fake_categories(_client: httpx.AsyncClient, distribution: str) -> list[str]:
        assert distribution == "paper"
        return ["economy", "utility"]

    async def fake_versions(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        project_id: str,
    ) -> list[ProjectVersion]:
        assert project_id == "proj"
        return [
            ProjectVersion(
                version_id="ver-1",
                version_number="1.2.3",
                version_type="release",
                date_published="2026-06-01T00:00:00Z",
                game_versions=["1.21.1"],
                loaders=["paper"],
            )
        ]

    monkeypatch.setattr("blockstead.app.modrinth_categories", fake_categories)
    monkeypatch.setattr("blockstead.app.modrinth_versions", fake_versions)
    categories = client.get(f"/api/v1/profiles/{paper_profile}/catalog/categories", headers=headers)
    assert categories.status_code == 200
    assert categories.json()["categories"] == ["economy", "utility"]

    versions = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/versions?project_id=proj", headers=headers
    )
    assert versions.status_code == 200
    assert versions.json()["versions"][0]["version_id"] == "ver-1"

    hostile = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/versions?project_id=..%2Fetc", headers=headers
    )
    assert hostile.status_code == 422


def test_update_check_and_apply(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    plugins = root / "paper-server" / "plugins"
    plugins.mkdir()
    (plugins / "old-plugin-1.0.jar").write_bytes(b"old bytes")
    (plugins / "homemade.jar").write_bytes(b"private plugin")
    record_local_files(plugins, ["old-plugin-1.0.jar"])
    world = root / "paper-server" / "world"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world")
    old_hash = hashlib.sha512(b"old bytes").hexdigest()
    new_jar = jar_bytes()
    dependency_jar = jar_bytes()

    planned = PlannedFile(
        project_id="proj",
        version_id="ver-2",
        version_number="2.0",
        file_name="old-plugin-2.0.jar",
        url="https://cdn.example/new.jar",
        checksum_algorithm="sha512",
        checksum=hashlib.sha512(new_jar).hexdigest(),
        required_by=None,
    )
    dependency = PlannedFile(
        project_id="core",
        version_id="core-3",
        version_number="3.0",
        file_name="new-core-3.0.jar",
        url="https://cdn.example/core.jar",
        checksum_algorithm="sha512",
        checksum=hashlib.sha512(dependency_jar).hexdigest(),
        required_by="old-plugin-2.0.jar",
    )

    async def fake_check(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        hashes: list[str],
    ) -> dict[str, PlannedFile | None]:
        assert distribution == "paper"
        assert old_hash in hashes
        return {old_hash: planned}

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        assert url in {"https://cdn.example/new.jar", "https://cdn.example/core.jar"}
        raw = new_jar if url.endswith("/new.jar") else dependency_jar
        (directory / file_name).write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        project_id: str,
        version_id: str | None = None,
    ) -> list[PlannedFile]:
        assert (distribution, minecraft_version, project_id, version_id) == (
            "paper",
            "1.21.1",
            "proj",
            "ver-2",
        )
        return [planned, dependency]

    monkeypatch.setattr("blockstead.app.modrinth_check_updates", fake_check)
    monkeypatch.setattr("blockstead.app.plan_install", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)

    check = client.get(f"/api/v1/profiles/{paper_profile}/extensions/updates", headers=headers)
    assert check.status_code == 200
    body = check.json()
    assert body["checked"] == 2
    assert body["unknown"] == ["homemade.jar"]
    assert body["updates"] == [
        {
            "file_name": "old-plugin-1.0.jar",
            "installed_version": None,
            "new_version_number": "2.0",
            "new_file_name": "old-plugin-2.0.jar",
            "project_id": "proj",
            "version_id": "ver-2",
        }
    ]

    backup = client.post(f"/api/v1/profiles/{paper_profile}/backups", headers=headers)
    assert backup.status_code == 201
    reviewed = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update-review",
        headers=headers,
        json={"file_name": "old-plugin-1.0.jar"},
    )
    assert reviewed.status_code == 200
    review = reviewed.json()
    assert review["review"]["dependencies"] == ["new-core-3.0.jar"]
    assert review["review"]["required_java_major"] == 21
    assert review["review"]["restart_required"] is True
    assert review["maintenance_plan"]["protection"]["verified"] is True

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update",
        headers=headers,
        json={
            "file_name": "old-plugin-1.0.jar",
            "review_id": review["review"]["review_id"],
            "maintenance_plan_id": review["maintenance_plan"]["plan_id"],
        },
    )
    assert applied.status_code == 200
    assert applied.json()["file_name"] == "old-plugin-2.0.jar"
    assert applied.json()["replaced"] == "old-plugin-1.0.jar"
    assert (plugins / "old-plugin-2.0.jar").is_file()
    assert applied.json()["dependencies_installed"] == ["new-core-3.0.jar"]
    assert (plugins / "new-core-3.0.jar").is_file()
    assert not (plugins / "old-plugin-1.0.jar").exists()
    recovery_id = applied.json()["recovery_id"]
    available = client.get(
        f"/api/v1/profiles/{paper_profile}/extensions/update-recoveries",
        headers=headers,
    )
    assert available.status_code == 200, available.text
    assert available.json()["recoveries"][0]["recovery_id"] == recovery_id

    recovered = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update-recovery/{recovery_id}",
        headers=headers,
    )
    assert recovered.status_code == 200
    assert (plugins / "old-plugin-1.0.jar").read_bytes() == b"old bytes"
    assert not (plugins / "old-plugin-2.0.jar").exists()
    assert not (plugins / "new-core-3.0.jar").exists()
    available_after = client.get(
        f"/api/v1/profiles/{paper_profile}/extensions/update-recoveries",
        headers=headers,
    )
    assert available_after.json()["recoveries"] == []
    restored_origin = load_origin_map(plugins)["old-plugin-1.0.jar"]
    assert restored_origin.source == "local"
    assert restored_origin.verified is False

    reviewed_again = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update-review",
        headers=headers,
        json={"file_name": "old-plugin-1.0.jar"},
    )
    assert reviewed_again.status_code == 200
    second_review = reviewed_again.json()
    session_class = client.app.state.session_factory.class_
    original_commit = session_class.commit
    fail_next_commit = True

    def fail_commit_once(session: object) -> None:
        nonlocal fail_next_commit
        if fail_next_commit:
            fail_next_commit = False
            raise SQLAlchemyError("forced commit failure")
        original_commit(session)

    monkeypatch.setattr(session_class, "commit", fail_commit_once)
    failed_apply = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update",
        headers=headers,
        json={
            "file_name": "old-plugin-1.0.jar",
            "review_id": second_review["review"]["review_id"],
            "maintenance_plan_id": second_review["maintenance_plan"]["plan_id"],
        },
    )
    assert failed_apply.status_code == 500
    assert (
        "previous extension version was restored"
        in failed_apply.json()["error"]["message"]
    )
    assert (plugins / "old-plugin-1.0.jar").read_bytes() == b"old bytes"
    assert not (plugins / "old-plugin-2.0.jar").exists()
    assert not (plugins / "new-core-3.0.jar").exists()

    missing = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update-review",
        headers=headers,
        json={"file_name": "nowhere.jar"},
    )
    assert missing.status_code == 404


def test_hangar_source_dispatch_and_install(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    captured: dict[str, object] = {}

    async def fake_hangar_search(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        query: str,
        categories: list[str] | None = None,
        sort: str = "relevance",
        offset: int = 0,
    ) -> SearchPage:
        captured["search"] = (distribution, query)
        return SearchPage(projects=[], total=0, offset=0, limit=20)

    async def fake_hangar_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        project_id: str,
        version_id: str | None = None,
    ) -> list[PlannedFile]:
        captured["plan"] = (distribution, project_id, version_id)
        return [
            PlannedFile(
                project_id=project_id,
                version_id="1.2.3",
                version_number="1.2.3",
                file_name="essentials-1.2.3.jar",
                url="https://hangar.papermc.io/files/essentials-1.2.3.jar",
                checksum_algorithm="sha256",
                checksum="d" * 64,
                required_by=None,
            )
        ]

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        checksum_algorithm: str | None,
        checksum: str | None,
    ) -> str:
        (directory / file_name).write_bytes(jar_bytes())
        return "e" * 64

    monkeypatch.setattr("blockstead.app.hangar_search", fake_hangar_search)
    monkeypatch.setattr("blockstead.app.hangar_plan_install", fake_hangar_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)

    searched = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/search?source=hangar&query=essentials",
        headers=headers,
    )
    assert searched.status_code == 200
    assert searched.json()["source"] == "hangar"
    assert captured["search"] == ("paper", "essentials")

    categories = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/categories?source=hangar", headers=headers
    )
    assert categories.status_code == 200
    assert "economy" in categories.json()["categories"]

    installed = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "EssentialsX/Essentials", "source": "hangar"},
    )
    assert installed.status_code == 201
    assert captured["plan"] == ("paper", "EssentialsX/Essentials", None)
    assert (root / "paper-server" / "plugins" / "essentials-1.2.3.jar").is_file()

    bogus = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/search?source=bogus&query=x", headers=headers
    )
    assert bogus.status_code == 422

    slash_for_modrinth = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "owner/slug", "source": "modrinth"},
    )
    assert slash_for_modrinth.status_code == 422


def test_curseforge_key_lifecycle_and_dispatch(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    captured: dict[str, object] = {}

    async def fake_cf_search(
        _client: httpx.AsyncClient,
        api_key: str | None,
        distribution: str,
        minecraft_version: str | None,
        query: str,
        categories: list[str] | None = None,
        sort: str = "relevance",
        offset: int = 0,
    ) -> SearchPage:
        captured["key"] = api_key
        captured["distribution"] = distribution
        return SearchPage(projects=[], total=0, offset=0, limit=20)

    monkeypatch.setattr("blockstead.app.curseforge_search", fake_cf_search)

    status = client.get("/api/v1/settings/curseforge", headers=headers)
    assert status.status_code == 200 and status.json() == {"configured": False}

    client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/search?source=curseforge&query=jei",
        headers=headers,
    )
    assert captured["key"] is None

    stored = client.put(
        "/api/v1/settings/curseforge", headers=headers, json={"api_key": "cf-key-abc123"}
    )
    assert stored.status_code == 200 and stored.json() == {"configured": True}
    assert "cf-key-abc123" not in stored.text.replace("configured", "")

    client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/search?source=curseforge&query=jei",
        headers=headers,
    )
    assert captured["key"] == "cf-key-abc123"
    assert captured["distribution"] == "paper"

    cleared = client.delete("/api/v1/settings/curseforge", headers=headers)
    assert cleared.status_code == 200 and cleared.json() == {"configured": False}
    assert client.get("/api/v1/settings/curseforge", headers=headers).json() == {
        "configured": False
    }

    whitespace = client.put(
        "/api/v1/settings/curseforge", headers=headers, json={"api_key": "has spaces"}
    )
    assert whitespace.status_code == 422


def test_install_downloads_planned_files(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    downloaded_jar = jar_bytes()
    planned = [
        PlannedFile(
            project_id="proj",
            version_id="ver",
            version_number="1.0",
            file_name="thing.jar",
            url="https://cdn.example/thing.jar",
            checksum_algorithm="sha512",
            checksum=hashlib.sha512(downloaded_jar).hexdigest(),
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
        (directory / file_name).write_bytes(downloaded_jar)
        return hashlib.sha256(downloaded_jar).hexdigest()

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
    assert again.status_code == 201
    assert again.json()["skipped"] == ["thing.jar"]


def test_install_discards_a_checksum_matching_non_jar_payload(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    payload = b"<!doctype html>not a mod"
    planned = [
        PlannedFile(
            project_id="proj",
            version_id="ver",
            version_number="1.0",
            file_name="not-a-mod.jar",
            url="https://cdn.example/not-a-mod.jar",
            checksum_algorithm="sha512",
            checksum=hashlib.sha512(payload).hexdigest(),
            required_by=None,
        )
    ]

    async def fake_plan(*_args: object, **_kwargs: object) -> list[PlannedFile]:
        return planned

    async def fake_download(
        _client: httpx.AsyncClient,
        _url: str,
        directory: Path,
        file_name: str,
        _algorithm: str | None,
        _checksum: str | None,
    ) -> str:
        (directory / file_name).write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr("blockstead.app.plan_install", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)
    response = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "proj"},
    )
    assert response.status_code == 400
    assert "valid jar" in response.json()["error"]["message"]
    plugins = root / "paper-server" / "plugins"
    assert not (plugins / "not-a-mod.jar").exists()
    assert not list(plugins.glob(".blockstead-install-*"))


def test_failed_dependency_download_does_not_change_the_live_loadout(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    planned = [
        PlannedFile(
            project_id="project",
            version_id="one",
            version_number="1",
            file_name="one.jar",
            url="https://cdn.example/one.jar",
            checksum_algorithm="sha512",
            checksum="a" * 128,
            required_by=None,
        ),
        PlannedFile(
            project_id="dependency",
            version_id="two",
            version_number="1",
            file_name="two.jar",
            url="https://cdn.example/two.jar",
            checksum_algorithm="sha512",
            checksum="b" * 128,
            required_by="one.jar",
        ),
    ]

    async def fake_plan(*_args: object, **_kwargs: object) -> list[PlannedFile]:
        return planned

    async def fake_download(
        _client: httpx.AsyncClient,
        url: str,
        directory: Path,
        file_name: str,
        _algorithm: str | None,
        _checksum: str | None,
    ) -> str:
        if url.endswith("two.jar"):
            from blockstead.provisioning import ProvisionError

            raise ProvisionError("second download failed")
        (directory / file_name).write_bytes(jar_bytes())
        return "c" * 64

    monkeypatch.setattr("blockstead.app.plan_install", fake_plan)
    monkeypatch.setattr("blockstead.app.download_verified_file", fake_download)
    response = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/install",
        headers=headers,
        json={"project_id": "project"},
    )

    assert response.status_code == 400
    plugins = root / "paper-server" / "plugins"
    assert not (plugins / "one.jar").exists()
    assert not (plugins / "two.jar").exists()


def test_squaremap_low_resource_profile_is_backed_up_and_health_is_explicit(
    api: tuple[TestClient, Path], headers: dict[str, str], paper_profile: str
) -> None:
    client, root = api
    config = root / "paper-server" / "plugins" / "squaremap" / "config.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "settings:\n"
        "  internal-webserver:\n"
        "    enabled: true\n"
        "    bind: 0.0.0.0\n"
        "    port: 8123\n"
        "world-settings:\n"
        "  default:\n"
        "    map:\n"
        "      max-render-threads: 4\n"
        "      background-render:\n"
        "        max-render-threads: 2\n",
        encoding="utf-8",
    )

    before = client.get(f"/api/v1/profiles/{paper_profile}/shared-map", headers=headers)
    assert before.status_code == 200
    assert before.json()["health"]["state"] == "not_running"

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/shared-map/low-resource", headers=headers
    )

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["normal_render_threads"] == body["background_render_threads"] == 1
    assert (root / "paper-server" / body["backup_path"]).is_file()
    assert "max-render-threads: 1" in config.read_text(encoding="utf-8")
