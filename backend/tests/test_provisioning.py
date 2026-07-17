import hashlib
import json
from pathlib import Path

import httpx
import pytest

from blockstead.provisioning import (
    FABRIC_INSTALLER,
    FORGE_MAVEN,
    FORGE_PROMOTIONS,
    MOJANG_MANIFEST,
    NEOFORGE_MAVEN,
    NEOFORGE_METADATA,
    PAPER_BUILDS,
    QUILT_INSTALLER,
    QUILT_INSTALLER_MAVEN,
    QUILT_LOADER,
    ProvisionError,
    list_versions,
    provision_profile,
    resolve_plan,
)

JAR_BYTES = b"not a real jar, just deterministic test bytes"
JAR_SHA1 = hashlib.sha1(JAR_BYTES).hexdigest()  # noqa: S324
JAR_SHA256 = hashlib.sha256(JAR_BYTES).hexdigest()

VERSION_DETAIL_URL = "https://piston-meta.example/1.21.1.json"
VANILLA_JAR_URL = "https://piston-data.example/server.jar"
PAPER_JAR_URL = "https://fill-data.example/paper-1.21.1-10.jar"
NEOFORGE_LOADER = "21.1.77"
NEOFORGE_INSTALLER_URL = (
    f"{NEOFORGE_MAVEN}/{NEOFORGE_LOADER}/"
    f"neoforge-{NEOFORGE_LOADER}-installer.jar"
)
FORGE_COORDINATE = "1.20.1-47.4.10"
FORGE_INSTALLER_URL = (
    f"{FORGE_MAVEN}/{FORGE_COORDINATE}/forge-{FORGE_COORDINATE}-installer.jar"
)
QUILT_INSTALLER_VERSION = "0.12.0"
QUILT_INSTALLER_URL = QUILT_INSTALLER_MAVEN.format(installer=QUILT_INSTALLER_VERSION)

RESPONSES: dict[str, object] = {
    MOJANG_MANIFEST: {
        "versions": [
            {"id": "1.21.1", "type": "release", "url": VERSION_DETAIL_URL},
            {"id": "24w33a", "type": "snapshot", "url": "https://piston-meta.example/s.json"},
        ]
    },
    VERSION_DETAIL_URL: {"downloads": {"server": {"url": VANILLA_JAR_URL, "sha1": JAR_SHA1}}},
    PAPER_BUILDS.format(version="1.21.1"): [
        {
            "id": 9,
            "channel": "STABLE",
            "downloads": {
                "server:default": {
                    "name": "paper-1.21.1-9.jar",
                    "url": "https://fill-data.example/old.jar",
                    "checksums": {"sha256": "0" * 64},
                }
            },
        },
        {
            "id": 10,
            "channel": "STABLE",
            "downloads": {
                "server:default": {
                    "name": "paper-1.21.1-10.jar",
                    "url": PAPER_JAR_URL,
                    "checksums": {"sha256": JAR_SHA256},
                }
            },
        },
    ],
    "https://meta.fabricmc.net/v2/versions/loader/1.21.1": [
        {"loader": {"version": "0.16.9", "stable": False}},
        {"loader": {"version": "0.16.5", "stable": True}},
    ],
    FABRIC_INSTALLER: [{"version": "1.0.1", "stable": True}],
    FORGE_PROMOTIONS: {"promos": {"1.20.1-recommended": "47.4.10"}},
    f"{FORGE_INSTALLER_URL}.sha1": JAR_SHA1,
    NEOFORGE_METADATA: (
        "<metadata><versioning><versions><version>21.1.76-beta</version>"
        "<version>21.1.77</version></versions></versioning></metadata>"
    ),
    f"{NEOFORGE_INSTALLER_URL}.sha1": JAR_SHA1,
    QUILT_LOADER.format(version="1.21.1"): [
        {"loader": {"version": "0.29.0", "stable": True}}
    ],
    QUILT_INSTALLER: [{"version": QUILT_INSTALLER_VERSION, "stable": True}],
    f"{QUILT_INSTALLER_URL}.sha1": JAR_SHA1,
}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url in {VANILLA_JAR_URL, PAPER_JAR_URL}:
        return httpx.Response(200, content=JAR_BYTES)
    if url in RESPONSES:
        payload = RESPONSES[url]
        if isinstance(payload, str):
            return httpx.Response(200, text=payload)
        return httpx.Response(200, json=json.loads(json.dumps(payload)))
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_vanilla_plan_uses_mojang_checksum(client: httpx.AsyncClient) -> None:
    plan = await resolve_plan(client, "vanilla", "1.21.1")
    assert plan.url == VANILLA_JAR_URL
    assert plan.checksum_algorithm == "sha1" and plan.checksum == JAR_SHA1
    assert plan.file_name == "server.jar"


async def test_paper_plan_picks_newest_stable_build(client: httpx.AsyncClient) -> None:
    plan = await resolve_plan(client, "paper", "1.21.1")
    assert plan.url == PAPER_JAR_URL
    assert plan.checksum == JAR_SHA256
    assert plan.file_name == "paper-1.21.1-10.jar"


async def test_fabric_plan_has_no_publisher_checksum(client: httpx.AsyncClient) -> None:
    plan = await resolve_plan(client, "fabric", "1.21.1")
    assert "0.16.5" in plan.url and "1.0.1" in plan.url
    assert plan.checksum is None
    assert any("checksum" in note for note in plan.notes)


async def test_neoforge_plan_uses_official_installer(client: httpx.AsyncClient) -> None:
    plan = await resolve_plan(client, "neoforge", "1.21.1")
    assert plan.loader_version == NEOFORGE_LOADER
    assert plan.url == NEOFORGE_INSTALLER_URL
    assert plan.checksum == JAR_SHA1


async def test_forge_and_quilt_plans_use_official_installers(
    client: httpx.AsyncClient,
) -> None:
    forge = await resolve_plan(client, "forge", "1.20.1")
    assert forge.loader_version == "47.4.10"
    assert forge.url == FORGE_INSTALLER_URL
    quilt = await resolve_plan(client, "quilt", "1.21.1")
    assert quilt.loader_version == "0.29.0"
    assert quilt.url == QUILT_INSTALLER_URL


async def test_unknown_version_is_refused(client: httpx.AsyncClient) -> None:
    with pytest.raises(ProvisionError, match="does not list"):
        await resolve_plan(client, "vanilla", "9.9.9")


async def test_list_versions_vanilla_releases_only(client: httpx.AsyncClient) -> None:
    assert await list_versions(client, "vanilla") == ["1.21.1"]


async def test_provision_places_verified_file(client: httpx.AsyncClient, tmp_path: Path) -> None:
    result = await provision_profile(client, tmp_path, "family-server", "vanilla", "1.21.1")
    target = tmp_path / "family-server"
    assert (target / "server.jar").read_bytes() == JAR_BYTES
    assert result.sha256 == JAR_SHA256
    assert not list(target.glob(".*.part"))
    assert not (target / "eula.txt").exists()


async def test_checksum_mismatch_discards_download(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    bad = dict(RESPONSES[VERSION_DETAIL_URL])  # type: ignore[arg-type]
    bad["downloads"] = {"server": {"url": VANILLA_JAR_URL, "sha1": "f" * 40}}
    original = RESPONSES[VERSION_DETAIL_URL]
    RESPONSES[VERSION_DETAIL_URL] = bad
    try:
        with pytest.raises(ProvisionError, match="checksum"):
            await provision_profile(client, tmp_path, "bad-server", "vanilla", "1.21.1")
    finally:
        RESPONSES[VERSION_DETAIL_URL] = original
    assert not (tmp_path / "bad-server").exists()


async def test_directory_name_and_collision_rules(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    with pytest.raises(ProvisionError, match="Folder names"):
        await provision_profile(client, tmp_path, "../escape", "vanilla", "1.21.1")
    with pytest.raises(ProvisionError, match="Folder names"):
        await provision_profile(client, tmp_path, "Has Spaces", "vanilla", "1.21.1")
    (tmp_path / "taken").mkdir()
    with pytest.raises(ProvisionError, match="already exists"):
        await provision_profile(client, tmp_path, "taken", "vanilla", "1.21.1")
