import json

import httpx
import pytest

from blockstead.hangar import (
    HANGAR_API,
    HangarError,
    list_categories,
    list_project_versions,
    plan_install,
    search,
)

SEARCH_RESULT = {
    "pagination": {"count": 37, "limit": 20, "offset": 0},
    "result": [
        {
            "name": "Essentials",
            "namespace": {"owner": "EssentialsX", "slug": "Essentials"},
            "description": "The essential plugin suite.",
            "stats": {"downloads": 500000, "stars": 900},
            "avatarUrl": "https://hangar.papermc.io/avatar.png",
            "category": "admin_tools",
        },
        {"name": "broken record with no namespace"},
    ],
}

VERSIONS_RESULT = {
    "pagination": {"count": 2, "limit": 20, "offset": 0},
    "result": [
        {
            "name": "2.21.0",
            "createdAt": "2026-05-20T10:00:00Z",
            "channel": {"name": "Release"},
            "downloads": {
                "PAPER": {
                    "downloadUrl": "https://hangar.papermc.io/files/Essentials-2.21.0.jar",
                    "fileInfo": {
                        "name": "Essentials-2.21.0.jar",
                        "sha256Hash": "a" * 64,
                        "sizeBytes": 4096,
                    },
                }
            },
            "platformDependencies": {"PAPER": ["1.21.1", "1.21.4"]},
            "pluginDependencies": {
                "PAPER": [
                    {"name": "Vault", "required": True},
                    {"name": "PlaceholderAPI", "required": False},
                ]
            },
        },
        {
            "name": "2.22.0-beta",
            "createdAt": "2026-06-01T10:00:00Z",
            "channel": {"name": "Beta"},
            "downloads": {
                "PAPER": {"externalUrl": "https://example.com/essentials-beta.jar"}
            },
            "platformDependencies": {"PAPER": ["1.21.4"]},
        },
    ],
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url).split("?")[0]
    if url == f"{HANGAR_API}/projects":
        params = request.url.params
        assert params["platform"] == "PAPER"
        assert params["query"] == "essentials"
        return httpx.Response(200, json=SEARCH_RESULT)
    if url == f"{HANGAR_API}/projects/EssentialsX/Essentials/versions":
        assert request.url.params["platform"] == "PAPER"
        return httpx.Response(200, json=VERSIONS_RESULT)
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_search_maps_projects_and_pagination(client: httpx.AsyncClient) -> None:
    page = await search(client, "paper", "1.21.1", "essentials")
    assert page.total == 37
    assert len(page.projects) == 1
    project = page.projects[0]
    assert project.project_id == "EssentialsX/Essentials"
    assert project.source == "hangar"
    assert project.author == "EssentialsX"
    assert project.page_url == "https://hangar.papermc.io/EssentialsX/Essentials"


async def test_search_refuses_mod_loaders(client: httpx.AsyncClient) -> None:
    with pytest.raises(HangarError, match="Paper-family"):
        await search(client, "fabric", "1.21.1", "essentials")


async def test_search_sort_mapping() -> None:
    calls: list[dict[str, str]] = []

    def capture(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=SEARCH_RESULT)

    client = httpx.AsyncClient(transport=httpx.MockTransport(capture))
    await search(client, "paper", None, "essentials", sort="follows")
    assert calls[-1]["sort"] == "stars"
    await search(client, "paper", None, "essentials", sort="relevance")
    assert "sort" not in calls[-1]
    with pytest.raises(HangarError, match="sort order"):
        await search(client, "paper", None, "essentials", sort="bogus")


async def test_categories_are_static(client: httpx.AsyncClient) -> None:
    names = await list_categories(client, "paper")
    assert "economy" in names and "admin_tools" in names
    with pytest.raises(HangarError):
        await list_categories(client, "forge")


async def test_versions_expose_external_and_dependencies(client: httpx.AsyncClient) -> None:
    versions = await list_project_versions(client, "paper", "1.21.1", "EssentialsX/Essentials")
    assert [item.version_id for item in versions] == ["2.21.0", "2.22.0-beta"]
    release = versions[0]
    assert release.version_type == "release"
    assert release.game_versions == ["1.21.1", "1.21.4"]
    assert release.required_plugins == ["Vault"]
    assert release.external_url is None
    assert versions[1].external_url == "https://example.com/essentials-beta.jar"


async def test_plan_prefers_release_and_verifies(client: httpx.AsyncClient) -> None:
    planned = await plan_install(client, "paper", "1.21.1", "EssentialsX/Essentials")
    assert len(planned) == 1
    assert planned[0].file_name == "Essentials-2.21.0.jar"
    assert planned[0].checksum_algorithm == "sha256"
    assert planned[0].checksum == "a" * 64
    assert planned[0].required_plugins == ["Vault"]


async def test_plan_refuses_external_files(client: httpx.AsyncClient) -> None:
    with pytest.raises(HangarError, match="hosted outside Hangar"):
        await plan_install(client, "paper", "1.21.1", "EssentialsX/Essentials", "2.22.0-beta")


async def test_plan_refuses_a_file_without_a_published_checksum() -> None:
    records = json.loads(json.dumps(VERSIONS_RESULT))
    records["result"][0]["downloads"]["PAPER"]["fileInfo"].pop("sha256Hash")

    def missing_hash(request: httpx.Request) -> httpx.Response:
        if str(request.url).split("?")[0].endswith("/versions"):
            return httpx.Response(200, json=records)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(missing_hash))
    with pytest.raises(HangarError, match="checksum"):
        await plan_install(client, "paper", "1.21.1", "EssentialsX/Essentials")


async def test_plan_refuses_unknown_version(client: httpx.AsyncClient) -> None:
    with pytest.raises(HangarError, match="does not suit"):
        await plan_install(client, "paper", "1.21.1", "EssentialsX/Essentials", "9.9.9")


async def test_hostile_project_ids_are_refused(client: httpx.AsyncClient) -> None:
    for hostile in ("../../etc", "a/b/c", "a b/c", "", "owner/"):
        with pytest.raises(HangarError):
            await list_project_versions(client, "paper", "1.21.1", hostile)
