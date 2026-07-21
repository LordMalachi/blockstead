import hashlib
import json

import httpx
import pytest

from blockstead.modrinth import (
    MODRINTH_API,
    ModrinthError,
    check_updates,
    list_categories,
    list_project_versions,
    plan_install,
    search,
)
from blockstead.provisioning import download_verified_file

JAR_BYTES = b"deterministic mod bytes"
JAR_SHA512 = hashlib.sha512(JAR_BYTES).hexdigest()
MOD_URL = "https://cdn.modrinth.example/cool-tech.jar"
DEP_URL = "https://cdn.modrinth.example/cool-core.jar"


def version_record(
    project_id: str,
    version_id: str,
    file_name: str,
    url: str,
    dependencies: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "id": version_id,
        "project_id": project_id,
        "version_number": "1.0.0",
        "version_type": "release",
        "loaders": ["fabric"],
        "files": [
            {
                "url": url,
                "filename": file_name,
                "primary": True,
                "hashes": {"sha512": JAR_SHA512, "sha1": "unused"},
            }
        ],
        "dependencies": dependencies or [],
    }


ROOT = version_record(
    "proj-tech",
    "ver-tech",
    "cool-tech-1.0.0.jar",
    MOD_URL,
    [
        {"project_id": "proj-core", "dependency_type": "required"},
        {"project_id": "proj-optional", "dependency_type": "optional"},
    ],
)
DEP = version_record("proj-core", "ver-core", "cool-core-2.0.0.jar", DEP_URL)

SEARCH_HITS = {
    "hits": [
        {
            "project_id": "proj-tech",
            "slug": "cool-tech",
            "title": "Cool Tech",
            "description": "Adds cool technology.",
            "downloads": 12345,
        }
    ],
    "total_hits": 64,
}

CATEGORY_TAGS = [
    {"name": "technology", "project_type": "mod", "header": "categories"},
    {"name": "optimization", "project_type": "mod", "header": "categories"},
    {"name": "kitchen-sink", "project_type": "modpack", "header": "categories"},
    {"name": "16x", "project_type": "resourcepack", "header": "resolutions"},
]


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url).split("?")[0]
    if url == f"{MODRINTH_API}/search":
        facets = json.loads(dict(request.url.params)["facets"])
        assert ["project_type:mod"] in facets
        return httpx.Response(200, json=SEARCH_HITS)
    if url == f"{MODRINTH_API}/tag/category":
        return httpx.Response(200, json=CATEGORY_TAGS)
    if url == f"{MODRINTH_API}/project/proj-tech/version":
        params = dict(request.url.params)
        assert json.loads(params["loaders"]) == ["fabric"]
        assert json.loads(params["game_versions"]) == ["1.21.1"]
        return httpx.Response(200, json=[ROOT])
    if url == f"{MODRINTH_API}/project/proj-core/version":
        return httpx.Response(200, json=[DEP])
    if url == f"{MODRINTH_API}/version/ver-tech":
        return httpx.Response(200, json=ROOT)
    if url in {MOD_URL, DEP_URL}:
        return httpx.Response(200, content=JAR_BYTES)
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_search_maps_projects(client: httpx.AsyncClient) -> None:
    page = await search(client, "fabric", "1.21.1", "cool")
    assert page.projects[0].project_id == "proj-tech"
    assert page.projects[0].title == "Cool Tech"
    assert page.total == 64 and page.offset == 0 and page.limit == 20


async def test_search_refuses_vanilla(client: httpx.AsyncClient) -> None:
    with pytest.raises(ModrinthError, match="plugin or mod loader"):
        await search(client, "vanilla", "1.21.1", "cool")


async def test_search_applies_category_sort_and_offset() -> None:
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=SEARCH_HITS)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    page = await search(
        client,
        "fabric",
        "1.21.1",
        "cool",
        categories=["optimization", "Bad Name!"],
        sort="downloads",
        offset=40,
    )
    facets = json.loads(seen["facets"])
    assert ["categories:optimization"] in facets
    assert not any("Bad Name!" in str(group) for group in facets)
    assert seen["index"] == "downloads"
    assert seen["offset"] == "40"
    assert page.offset == 40


async def test_search_refuses_unknown_sort(client: httpx.AsyncClient) -> None:
    with pytest.raises(ModrinthError, match="sort order"):
        await search(client, "fabric", "1.21.1", "cool", sort="bogus")


async def test_list_categories_filters_by_project_type(client: httpx.AsyncClient) -> None:
    assert await list_categories(client, "fabric") == ["optimization", "technology"]
    # Plugins share the mod category list; Modrinth has no separate plugin tags.
    assert await list_categories(client, "paper") == ["optimization", "technology"]


async def test_list_project_versions_maps_records(client: httpx.AsyncClient) -> None:
    versions = await list_project_versions(client, "fabric", "1.21.1", "proj-tech")
    assert versions[0].version_id == "ver-tech"
    assert versions[0].version_number == "1.0.0"
    assert versions[0].version_type == "release"


async def test_plan_resolves_required_dependencies_only(client: httpx.AsyncClient) -> None:
    planned = await plan_install(client, "fabric", "1.21.1", "proj-tech")
    names = [item.file_name for item in planned]
    assert names == ["cool-tech-1.0.0.jar", "cool-core-2.0.0.jar"]
    assert planned[1].required_by == "cool-tech-1.0.0.jar"
    assert all(item.checksum_algorithm == "sha512" for item in planned)


async def test_planned_files_download_and_verify(client: httpx.AsyncClient, tmp_path) -> None:
    planned = await plan_install(client, "fabric", "1.21.1", "proj-tech", "ver-tech")
    for item in planned:
        sha256 = await download_verified_file(
            client, item.url, tmp_path, item.file_name, item.checksum_algorithm, item.checksum
        )
        assert (tmp_path / item.file_name).read_bytes() == JAR_BYTES
        assert sha256 == hashlib.sha256(JAR_BYTES).hexdigest()


async def test_wrong_loader_version_is_refused(client: httpx.AsyncClient) -> None:
    with pytest.raises(ModrinthError, match="does not support"):
        await plan_install(client, "paper", "1.21.1", "proj-tech", "ver-tech")


async def test_required_external_dependency_is_not_silently_dropped() -> None:
    external = version_record(
        "proj-tech",
        "ver-tech",
        "cool-tech-1.0.0.jar",
        MOD_URL,
        [{"file_name": "outside-library.jar", "dependency_type": "required"}],
    )

    def external_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).split("?")[0] == f"{MODRINTH_API}/project/proj-tech/version":
            return httpx.Response(200, json=[external])
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(external_handler))
    with pytest.raises(ModrinthError, match="outside Modrinth"):
        await plan_install(client, "fabric", "1.21.1", "proj-tech")


async def test_pinned_dependency_must_match_the_server() -> None:
    incompatible = version_record("proj-core", "wrong-core", "core.jar", DEP_URL)
    root = version_record(
        "proj-tech",
        "ver-tech",
        "cool-tech-1.0.0.jar",
        MOD_URL,
        [{"version_id": "wrong-core", "dependency_type": "required"}],
    )
    incompatible["loaders"] = ["forge"]

    def incompatible_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == f"{MODRINTH_API}/project/proj-tech/version":
            return httpx.Response(200, json=[root])
        if url == f"{MODRINTH_API}/version/wrong-core":
            return httpx.Response(200, json=incompatible)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(incompatible_handler))
    with pytest.raises(ModrinthError, match="required dependency.*loader"):
        await plan_install(client, "fabric", "1.21.1", "proj-tech")


async def test_check_updates_distinguishes_current_from_stale() -> None:
    stale_hash = "b" * 128
    current_hash = JAR_SHA512

    def update_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/version_files/update")
        body = json.loads(request.content)
        assert body["algorithm"] == "sha512"
        assert body["loaders"] == ["fabric"]
        assert body["game_versions"] == ["1.21.1"]
        return httpx.Response(
            200,
            json={
                stale_hash: ROOT,  # newest file hash differs from the installed one
                current_hash: ROOT,  # identical hash: already newest
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(update_handler))
    found = await check_updates(
        client, "fabric", "1.21.1", [stale_hash, current_hash, "c" * 128]
    )
    assert found[stale_hash] is not None
    assert found[stale_hash].file_name == "cool-tech-1.0.0.jar"
    assert found[current_hash] is None
    assert "c" * 128 not in found


async def test_check_updates_with_no_hashes_skips_network() -> None:
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made")

    client = httpx.AsyncClient(transport=httpx.MockTransport(failing_handler))
    assert await check_updates(client, "fabric", "1.21.1", []) == {}
