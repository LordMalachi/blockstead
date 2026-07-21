import hashlib
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.modrinth import PlannedFile, ProjectVersion, SearchPage


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
    categories = client.get(
        f"/api/v1/profiles/{paper_profile}/catalog/categories", headers=headers
    )
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
    old_hash = hashlib.sha512(b"old bytes").hexdigest()

    planned = PlannedFile(
        project_id="proj",
        version_id="ver-2",
        version_number="2.0",
        file_name="old-plugin-2.0.jar",
        url="https://cdn.example/new.jar",
        checksum_algorithm="sha512",
        checksum="f" * 128,
        required_by=None,
    )
    dependency = PlannedFile(
        project_id="core",
        version_id="core-3",
        version_number="3.0",
        file_name="new-core-3.0.jar",
        url="https://cdn.example/core.jar",
        checksum_algorithm="sha512",
        checksum="e" * 128,
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
        (directory / file_name).write_bytes(url.encode())
        return "a" * 64

    async def fake_plan(
        _client: httpx.AsyncClient,
        distribution: str,
        minecraft_version: str | None,
        project_id: str,
        version_id: str | None = None,
    ) -> list[PlannedFile]:
        assert (distribution, minecraft_version, project_id, version_id) == (
            "paper", "1.21.1", "proj", "ver-2"
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

    applied = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update",
        headers=headers,
        json={"file_name": "old-plugin-1.0.jar"},
    )
    assert applied.status_code == 200
    assert applied.json()["file_name"] == "old-plugin-2.0.jar"
    assert applied.json()["replaced"] == "old-plugin-1.0.jar"
    assert (plugins / "old-plugin-2.0.jar").is_file()
    assert applied.json()["dependencies_installed"] == ["new-core-3.0.jar"]
    assert (plugins / "new-core-3.0.jar").is_file()
    assert not (plugins / "old-plugin-1.0.jar").exists()

    missing = client.post(
        f"/api/v1/profiles/{paper_profile}/extensions/update",
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
        (directory / file_name).write_bytes(b"downloaded")
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


def test_failed_dependency_download_does_not_change_the_live_loadout(
    api: tuple[TestClient, Path],
    headers: dict[str, str],
    paper_profile: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, root = api
    planned = [
        PlannedFile(
            project_id="project", version_id="one", version_number="1", file_name="one.jar",
            url="https://cdn.example/one.jar", checksum_algorithm="sha512", checksum="a" * 128,
            required_by=None,
        ),
        PlannedFile(
            project_id="dependency", version_id="two", version_number="1", file_name="two.jar",
            url="https://cdn.example/two.jar", checksum_algorithm="sha512", checksum="b" * 128,
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
        (directory / file_name).write_bytes(b"first")
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
