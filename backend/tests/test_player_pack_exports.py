import io
import json
import zipfile
from datetime import UTC, datetime

import pytest

from blockstead.extensions import ExtensionEntry, ExtensionsView
from blockstead.loadout_lockfiles import ExtensionOrigin
from blockstead.player_pack_exports import (
    PlayerPackExportError,
    build_player_mrpack,
)

GENERATED = datetime(2026, 7, 28, 12, 30, 15, tzinfo=UTC)


def extension(name: str, sha: str, environment: str | None) -> ExtensionEntry:
    return ExtensionEntry(
        file_name=name,
        size_bytes=100,
        sha256=sha * 64,
        sha512=sha * 128,
        kind="fabric-mod",
        loaders=["fabric"],
        identifier=name.removesuffix(".jar"),
        display_name=name.removesuffix(".jar").title(),
        version="1.0.0",
        minecraft_constraint="1.21.1",
        environment=environment,
        dependencies=[],
        readable=True,
    )


def inventory(entries: list[ExtensionEntry]) -> ExtensionsView:
    return ExtensionsView(
        directory="mods",
        present=True,
        entries=entries,
        disabled_entries=[],
        warnings=[],
        truncated=False,
    )


def test_player_pack_includes_only_verified_client_downloads_and_never_jars() -> None:
    client = extension("client.jar", "a", "client")
    universal = extension("local-universal.jar", "b", "*")
    server = extension("server.jar", "c", "server")
    unknown = extension("mystery.jar", "d", None)
    origin = ExtensionOrigin(
        source="modrinth",
        project_id="client-project",
        version_id="client-version",
        download_url="https://cdn.modrinth.com/data/client/versions/1/client.jar",
        checksum_algorithm="sha512",
        checksum=client.sha512,
        verified=True,
    )

    result = build_player_mrpack(
        inventory([unknown, server, universal, client]),
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
        pack_name="Family Players",
        version_id="1.0.0",
        summary="Client files for the family server.",
        generated_at=GENERATED,
        origins={client.sha512 or "": origin},
    )

    assert result.index["dependencies"] == {
        "minecraft": "1.21.1",
        "fabric-loader": "0.16.5",
    }
    files = result.index["files"]
    assert isinstance(files, list)
    assert [item["path"] for item in files] == ["mods/client.jar"]
    assert files[0]["env"] == {"client": "required", "server": "unsupported"}
    assert [item.file_name for item in result.summary.manual_requirements] == [
        "local-universal.jar",
        "mystery.jar",
    ]
    assert [item.file_name for item in result.summary.excluded] == ["server.jar"]
    assert [item.code for item in result.summary.disclosures] == [
        "unknown_environment"
    ]

    with zipfile.ZipFile(io.BytesIO(result.archive)) as archive:
        assert sorted(archive.namelist()) == [
            "blockstead.export.json",
            "modrinth.index.json",
        ]
        assert not any(name.endswith(".jar") for name in archive.namelist())
        exported_index = json.loads(archive.read("modrinth.index.json"))
        manifest = json.loads(archive.read("blockstead.export.json"))
    assert exported_index == result.index
    assert manifest["generatedAt"] == "2026-07-28T12:30:15Z"
    assert len(manifest["manualRequirements"]) == 2


def test_player_pack_discloses_checksum_mismatch_instead_of_using_source() -> None:
    client = extension("client.jar", "a", "client")
    mismatched = ExtensionOrigin(
        source="modrinth",
        download_url="https://cdn.modrinth.com/data/client/versions/1/client.jar",
        checksum_algorithm="sha512",
        checksum="f" * 128,
        verified=True,
    )

    result = build_player_mrpack(
        inventory([client]),
        minecraft_version="1.21.1",
        distribution="fabric",
        loader_version="0.16.5",
        pack_name="Players",
        version_id="1",
        summary="Player files",
        generated_at=GENERATED,
        origins={client.file_name: mismatched},
    )

    assert result.index["files"] == []
    assert result.summary.manual_requirements[0].file_name == "client.jar"
    assert result.summary.disclosures[0].code == "unverified_download_source"


def test_player_pack_bytes_are_deterministic_and_require_loader_version() -> None:
    kwargs = {
        "minecraft_version": "1.21.1",
        "distribution": "fabric",
        "loader_version": "0.16.5",
        "pack_name": "Players",
        "version_id": "1",
        "summary": "Player files",
        "generated_at": GENERATED,
    }
    first = build_player_mrpack(inventory([]), **kwargs)
    second = build_player_mrpack(inventory([]), **kwargs)
    assert first.archive == second.archive

    with pytest.raises(PlayerPackExportError, match="loader version"):
        build_player_mrpack(
            inventory([]),
            **{**kwargs, "loader_version": None},
        )
