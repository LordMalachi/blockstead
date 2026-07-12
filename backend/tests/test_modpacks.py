import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

import blockstead.modpacks as modpacks_module
from blockstead.modpacks import (
    ModpackError,
    fetch_mrpack,
    install_modpack,
    parse_mrpack,
)
from blockstead.modrinth import MODRINTH_API

MOD_BYTES = b"mod jar bytes"
MOD_SHA512 = hashlib.sha512(MOD_BYTES).hexdigest()
MOD_URL = "https://cdn.modrinth.com/data/abc/mod-1.0.jar"
LAUNCHER_BYTES = b"fabric launcher bytes"
LAUNCHER_URL = "https://meta.fabricmc.net/v2/versions/loader/1.21.1/0.16.5/1.0.1/server/jar"


def build_mrpack(
    *,
    files: list[dict[str, object]] | None = None,
    dependencies: dict[str, str] | None = None,
    overrides: dict[str, bytes] | None = None,
) -> bytes:
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "name": "Adventure Pack",
        "versionId": "1.0.0",
        "dependencies": dependencies
        if dependencies is not None
        else {"minecraft": "1.21.1", "fabric-loader": "0.16.5"},
        "files": files
        if files is not None
        else [
            {
                "path": "mods/mod-1.0.jar",
                "downloads": [MOD_URL],
                "hashes": {"sha512": MOD_SHA512},
                "env": {"client": "required", "server": "required"},
            },
            {
                "path": "mods/client-shader.jar",
                "downloads": [MOD_URL],
                "hashes": {"sha512": MOD_SHA512},
                "env": {"client": "required", "server": "unsupported"},
            },
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("modrinth.index.json", json.dumps(index))
        for name, content in (overrides or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url).split("?")[0]
    if url == MOD_URL:
        return httpx.Response(200, content=MOD_BYTES)
    if url == LAUNCHER_URL:
        return httpx.Response(200, content=LAUNCHER_BYTES)
    if url == "https://meta.fabricmc.net/v2/versions/installer":
        return httpx.Response(200, json=[{"version": "1.0.1", "stable": True}])
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_skips_server_unsupported_files() -> None:
    index = parse_mrpack(build_mrpack())
    assert index.minecraft_version == "1.21.1"
    assert index.loader_version == "0.16.5"
    assert [item.path for item in index.files] == ["mods/mod-1.0.jar"]
    assert index.skipped_unsupported == ["mods/client-shader.jar"]


def test_parse_refuses_non_fabric_loaders() -> None:
    pack = build_mrpack(dependencies={"minecraft": "1.21.1", "neoforge": "21.1.77"})
    with pytest.raises(ModpackError, match="Neoforge"):
        parse_mrpack(pack)


def test_parse_refuses_traversal_and_bad_hosts() -> None:
    traversal = build_mrpack(
        files=[
            {
                "path": "../escape.jar",
                "downloads": [MOD_URL],
                "hashes": {"sha512": MOD_SHA512},
            }
        ]
    )
    with pytest.raises(ModpackError, match="unsafe file path"):
        parse_mrpack(traversal)
    bad_host = build_mrpack(
        files=[
            {
                "path": "mods/x.jar",
                "downloads": ["https://evil.example/x.jar"],
                "hashes": {"sha512": MOD_SHA512},
            }
        ]
    )
    with pytest.raises(ModpackError, match="allowed hosts"):
        parse_mrpack(bad_host)
    unhashed = build_mrpack(files=[{"path": "mods/x.jar", "downloads": [MOD_URL], "hashes": {}}])
    with pytest.raises(ModpackError, match="checksum"):
        parse_mrpack(unhashed)


async def test_install_caps_override_file_count(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    overrides = {f"overrides/config/{index}.txt": b"" for index in range(501)}
    with pytest.raises(ModpackError, match="override files"):
        await install_modpack(
            client, tmp_path, "too-many-overrides", build_mrpack(overrides=overrides)
        )
    assert not (tmp_path / "too-many-overrides").exists()


async def test_install_places_files_overrides_and_launcher(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    pack = build_mrpack(
        overrides={
            "overrides/config/mod.toml": b"setting = 1",
            "server-overrides/config/mod.toml": b"setting = 2",
            "overrides/eula.txt": b"eula=true",
        }
    )
    result = await install_modpack(client, tmp_path, "adventure", pack)
    target = tmp_path / "adventure"
    assert (target / "mods" / "mod-1.0.jar").read_bytes() == MOD_BYTES
    assert (target / "config" / "mod.toml").read_bytes() == b"setting = 2"
    assert (target / "fabric-server-launch.jar").read_bytes() == LAUNCHER_BYTES
    assert not (target / "eula.txt").exists()
    assert any("eula" in note.lower() for note in result.notes)
    assert result.minecraft_version == "1.21.1"
    assert result.skipped_unsupported == ["mods/client-shader.jar"]


async def test_failed_install_cleans_up(client: httpx.AsyncClient, tmp_path: Path) -> None:
    bad = build_mrpack(
        files=[
            {
                "path": "mods/x.jar",
                "downloads": [MOD_URL],
                "hashes": {"sha512": "f" * 128},
            }
        ]
    )
    with pytest.raises(Exception, match="checksum"):
        await install_modpack(client, tmp_path, "broken", bad)
    assert not (tmp_path / "broken").exists()


async def test_fetch_mrpack_verifies_published_hash(client: httpx.AsyncClient) -> None:
    pack = build_mrpack()

    def catalog_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == f"{MODRINTH_API}/project/pack-proj/version":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "pack-ver",
                        "project_id": "pack-proj",
                        "version_type": "release",
                        "files": [
                            {
                                "filename": "adventure-1.0.mrpack",
                                "url": "https://cdn.modrinth.com/pack.mrpack",
                                "primary": True,
                                "hashes": {"sha512": hashlib.sha512(pack).hexdigest()},
                            }
                        ],
                        "dependencies": [],
                    }
                ],
            )
        if url == "https://cdn.modrinth.com/pack.mrpack":
            return httpx.Response(200, content=pack)
        return httpx.Response(404)

    catalog = httpx.AsyncClient(transport=httpx.MockTransport(catalog_handler))
    data = await fetch_mrpack(catalog, "pack-proj", None)
    assert data == pack


@pytest.mark.parametrize(
    ("url", "hashes", "message"),
    [
        ("https://metadata.example/pack.mrpack", {"sha512": "a" * 128}, "allowed hosts"),
        ("https://cdn.modrinth.com/pack.mrpack", {}, "published checksum"),
    ],
)
async def test_fetch_mrpack_refuses_untrusted_catalog_files(
    url: str, hashes: dict[str, str], message: str
) -> None:
    def catalog_handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).split("?")[0] == f"{MODRINTH_API}/project/pack-proj/version":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "pack-ver",
                        "project_id": "pack-proj",
                        "version_type": "release",
                        "files": [
                            {
                                "filename": "pack.mrpack",
                                "url": url,
                                "primary": True,
                                "hashes": hashes,
                            }
                        ],
                    }
                ],
            )
        raise AssertionError("An unsafe or unverifiable catalog URL must not be requested")

    catalog = httpx.AsyncClient(transport=httpx.MockTransport(catalog_handler))
    with pytest.raises(ModpackError, match=message):
        await fetch_mrpack(catalog, "pack-proj", None)


async def test_fetch_mrpack_caps_streamed_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    pack = b"too-large"

    def catalog_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url).split("?")[0]
        if url == f"{MODRINTH_API}/project/pack-proj/version":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "pack-ver",
                        "project_id": "pack-proj",
                        "version_type": "release",
                        "files": [
                            {
                                "filename": "pack.mrpack",
                                "url": "https://cdn.modrinth.com/pack.mrpack",
                                "hashes": {"sha512": hashlib.sha512(pack).hexdigest()},
                            }
                        ],
                    }
                ],
            )
        if url == "https://cdn.modrinth.com/pack.mrpack":
            return httpx.Response(200, content=pack)
        return httpx.Response(404)

    monkeypatch.setattr(modpacks_module, "MAX_MRPACK_BYTES", 8)
    catalog = httpx.AsyncClient(transport=httpx.MockTransport(catalog_handler))
    with pytest.raises(ModpackError, match="larger"):
        await fetch_mrpack(catalog, "pack-proj", None)
