import httpx
import pytest

from blockstead.curseforge import (
    CURSEFORGE_API,
    CurseForgeError,
    list_categories,
    list_project_versions,
    plan_install,
    search,
)

KEY = "test-api-key-12345"

SEARCH_RESULT = {
    "data": [
        {
            "id": 238222,
            "name": "Just Enough Items",
            "slug": "jei",
            "summary": "View items and recipes.",
            "downloadCount": 999999,
            "logo": {"thumbnailUrl": "https://media.forgecdn.net/jei.png"},
            "authors": [{"name": "mezz"}],
            "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/jei"},
            "allowModDistribution": True,
        },
        {
            "id": 999999,
            "name": "OptedOut",
            "slug": "opted-out",
            "summary": "No automated downloads.",
            "downloadCount": 5,
            "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/opted-out"},
            "allowModDistribution": False,
        },
    ],
    "pagination": {"index": 0, "pageSize": 20, "resultCount": 2, "totalCount": 51},
}

CATEGORY_RESULT = {
    "data": [
        {"id": 420, "slug": "storage", "name": "Storage"},
        {"id": 421, "slug": "map-information", "name": "Map and Information"},
        {"id": 422, "slug": "Bad Slug!", "name": "Broken"},
    ]
}

FILES_RESULT = {
    "data": [
        {
            "id": 5001,
            "displayName": "jei-1.21.1-19.0.0.jar",
            "fileName": "jei-1.21.1-19.0.0.jar",
            "releaseType": 1,
            "fileDate": "2026-06-15T00:00:00Z",
            "downloadUrl": "https://edge.forgecdn.net/files/5001/jei.jar",
            "gameVersions": ["1.21.1", "Fabric"],
            "hashes": [
                {"value": "b" * 40, "algo": 1},
                {"value": "c" * 32, "algo": 2},
            ],
            "dependencies": [
                {"modId": 306612, "relationType": 3},
                {"modId": 777777, "relationType": 2},
            ],
        },
        {
            "id": 5002,
            "displayName": "jei-1.21.1-19.1.0-beta.jar",
            "fileName": "jei-1.21.1-19.1.0-beta.jar",
            "releaseType": 2,
            "fileDate": "2026-06-20T00:00:00Z",
            "downloadUrl": None,
            "gameVersions": ["1.21.1", "Fabric"],
            "hashes": [],
            "dependencies": [],
        },
    ]
}

DEP_FILES_RESULT = {
    "data": [
        {
            "id": 6001,
            "displayName": "fabric-api-0.100.0.jar",
            "fileName": "fabric-api-0.100.0.jar",
            "releaseType": 1,
            "fileDate": "2026-06-01T00:00:00Z",
            "downloadUrl": "https://edge.forgecdn.net/files/6001/fabric-api.jar",
            "gameVersions": ["1.21.1", "Fabric"],
            "hashes": [{"value": "d" * 40, "algo": 1}],
            "dependencies": [],
        }
    ]
}

MOD_RESULT = {
    "data": {
        "id": 238222,
        "slug": "jei",
        "links": {"websiteUrl": "https://www.curseforge.com/minecraft/mc-mods/jei"},
    }
}


def handler(request: httpx.Request) -> httpx.Response:
    assert request.headers.get("x-api-key") == KEY
    url = str(request.url).split("?")[0]
    if url == f"{CURSEFORGE_API}/mods/search":
        return httpx.Response(200, json=SEARCH_RESULT)
    if url == f"{CURSEFORGE_API}/categories":
        return httpx.Response(200, json=CATEGORY_RESULT)
    if url == f"{CURSEFORGE_API}/mods/238222":
        return httpx.Response(200, json=MOD_RESULT)
    if url == f"{CURSEFORGE_API}/mods/238222/files":
        return httpx.Response(200, json=FILES_RESULT)
    if url == f"{CURSEFORGE_API}/mods/306612/files":
        return httpx.Response(200, json=DEP_FILES_RESULT)
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_missing_key_is_refused(client: httpx.AsyncClient) -> None:
    with pytest.raises(CurseForgeError, match="API key"):
        await search(client, None, "fabric", "1.21.1", "jei")
    with pytest.raises(CurseForgeError, match="API key"):
        await list_categories(client, "", "fabric")


async def test_vanilla_has_no_curseforge_catalog(client: httpx.AsyncClient) -> None:
    with pytest.raises(CurseForgeError, match="does not have a CurseForge catalog"):
        await search(client, KEY, "vanilla", "1.21.1", "jei")


async def test_search_maps_projects_and_opt_out(client: httpx.AsyncClient) -> None:
    page = await search(client, KEY, "fabric", "1.21.1", "jei")
    assert page.total == 51
    jei = page.projects[0]
    assert jei.project_id == "238222"
    assert jei.source == "curseforge"
    assert jei.installable is True
    assert jei.page_url == "https://www.curseforge.com/minecraft/mc-mods/jei"
    opted_out = page.projects[1]
    assert opted_out.installable is False


async def test_search_params_for_paper_use_plugin_class() -> None:
    seen: dict[str, str] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=SEARCH_RESULT)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    await search(client, KEY, "paper", "1.21.1", "essentials", sort="downloads")
    assert seen["classId"] == "5"
    assert "modLoaderType" not in seen
    assert seen["sortField"] == "6"
    await search(client, KEY, "neoforge", None, "jei")
    assert seen["classId"] == "6"
    assert seen["modLoaderType"] == "6"


async def test_list_categories_returns_clean_slugs(client: httpx.AsyncClient) -> None:
    assert await list_categories(client, KEY, "fabric") == ["map-information", "storage"]


async def test_versions_mark_blocked_files_as_external(client: httpx.AsyncClient) -> None:
    versions = await list_project_versions(client, KEY, "fabric", "1.21.1", "238222")
    assert versions[0].version_id == "5001"
    assert versions[0].version_type == "release"
    assert versions[0].external_url is None
    assert versions[1].external_url == (
        "https://www.curseforge.com/minecraft/mc-mods/jei/files/5002"
    )


async def test_plan_resolves_required_dependencies(client: httpx.AsyncClient) -> None:
    planned = await plan_install(client, KEY, "fabric", "1.21.1", "238222")
    assert [item.file_name for item in planned] == [
        "jei-1.21.1-19.0.0.jar",
        "fabric-api-0.100.0.jar",
    ]
    assert planned[0].checksum_algorithm == "sha1"
    assert planned[0].checksum == "b" * 40
    assert planned[1].required_by == "jei-1.21.1-19.0.0.jar"


async def test_plan_refuses_blocked_download(client: httpx.AsyncClient) -> None:
    with pytest.raises(CurseForgeError, match="CurseForge"):
        await plan_install(client, KEY, "fabric", "1.21.1", "238222", "5002")


async def test_hostile_project_ids_are_refused(client: httpx.AsyncClient) -> None:
    for hostile in ("../etc", "abc", "1; drop", ""):
        with pytest.raises(CurseForgeError):
            await list_project_versions(client, KEY, "fabric", "1.21.1", hostile)
