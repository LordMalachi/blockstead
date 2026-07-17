import hashlib
import json

import httpx
import pytest

from blockstead.modrinth import (
    MODRINTH_API,
    ModrinthError,
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
    ]
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url).split("?")[0]
    if url == f"{MODRINTH_API}/search":
        facets = json.loads(dict(request.url.params)["facets"])
        assert ["project_type:mod"] in facets
        return httpx.Response(200, json=SEARCH_HITS)
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
    projects = await search(client, "fabric", "1.21.1", "cool")
    assert projects[0].project_id == "proj-tech"
    assert projects[0].title == "Cool Tech"


async def test_search_refuses_vanilla(client: httpx.AsyncClient) -> None:
    with pytest.raises(ModrinthError, match="plugin or mod loader"):
        await search(client, "vanilla", "1.21.1", "cool")


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
