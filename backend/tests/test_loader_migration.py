from pathlib import Path

import pytest

from blockstead.extensions import ExtensionEntry
from blockstead.loader_migration import (
    classify_extensions,
    copy_worlds,
    discover_world_roots,
    review_fingerprint,
    safe_level_name,
    uses_modern_paper_layout,
    world_copy_operations,
    world_roots,
)


def extension(loaders: list[str], *, environment: str = "*") -> ExtensionEntry:
    loader = loaders[0] if loaders else "unknown"
    kind = {
        "paper": "paper-plugin",
        "fabric": "fabric-mod",
        "forge": "forge-mod",
        "neoforge": "neoforge-mod",
        "quilt": "quilt-mod",
        "unknown": "unknown",
    }[loader]
    return ExtensionEntry(
        file_name=f"{loader}.jar",
        size_bytes=10,
        sha256="a" * 64,
        sha512="b" * 128,
        kind=kind,
        loaders=loaders,
        identifier=loader if loaders else None,
        display_name=loader.title(),
        version="1.0",
        minecraft_constraint="1.21.1",
        environment=environment,
        dependencies=[],
        readable=True,
    )


def test_world_copy_preserves_all_dimensions_and_leaves_source_unchanged(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    for name in ("family", "family_nether", "family_the_end"):
        root = source / name
        root.mkdir()
        (root / "level.dat").write_text(name, encoding="utf-8")
    roots = world_roots(source, "family")

    copied = copy_worlds(roots, target, "family", "paper", "paper", "1.21.1")

    assert copied == ["family", "family_nether", "family_the_end"]
    assert (target / "family" / "level.dat").read_text(encoding="utf-8") == "family"
    assert (target / "server.properties").read_text(encoding="utf-8") == "level-name=family\n"
    assert (source / "family" / "level.dat").read_text(encoding="utf-8") == "family"


def test_world_copy_server_properties_write_is_crash_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-write to the new profile's server.properties must never
    leave it truncated: the previous content (from the installer) survives
    and the write is retried whole or not at all."""

    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    root = source / "family"
    root.mkdir()
    (root / "level.dat").write_text("family", encoding="utf-8")
    (target / "server.properties").write_text(
        "motd=installer default\nlevel-name=world\n", encoding="utf-8"
    )
    roots = world_roots(source, "family")

    def failing_replace(src: object, dst: object) -> None:
        raise OSError("simulated crash during write")

    monkeypatch.setattr("blockstead.host_fs.os.replace", failing_replace)

    with pytest.raises(ValueError, match="could not be written"):
        copy_worlds(roots, target, "family", "paper", "paper", "1.21.1")

    monkeypatch.undo()
    properties = target / "server.properties"
    assert properties.read_text(encoding="utf-8") == "motd=installer default\nlevel-name=world\n"
    leftovers = [entry.name for entry in target.iterdir() if entry.name != "family"]
    assert leftovers == ["server.properties"]


def test_paper_dimensions_are_merged_for_mod_loaders(tmp_path: Path) -> None:
    source = tmp_path / "paper"
    target = tmp_path / "fabric"
    (source / "world").mkdir(parents=True)
    (source / "world_nether" / "DIM-1").mkdir(parents=True)
    (source / "world_the_end" / "DIM1").mkdir(parents=True)
    (source / "world_nether" / "DIM-1" / "level.dat").write_text("nether")
    (source / "world_the_end" / "DIM1" / "level.dat").write_text("end")
    target.mkdir()

    copy_worlds(
        world_roots(source, "world"), target, "world", "paper", "fabric", "1.21.1"
    )

    assert (target / "world" / "DIM-1" / "level.dat").read_text() == "nether"
    assert (target / "world" / "DIM1" / "level.dat").read_text() == "end"
    assert not (target / "world_nether").exists()


def test_vanilla_layout_is_kept_for_papers_supported_first_start_import(tmp_path: Path) -> None:
    source = tmp_path / "vanilla"
    target = tmp_path / "paper"
    (source / "world" / "DIM-1").mkdir(parents=True)
    (source / "world" / "DIM1").mkdir(parents=True)
    (source / "world" / "DIM-1" / "level.dat").write_text("nether")
    (source / "world" / "DIM1" / "level.dat").write_text("end")
    target.mkdir()

    copy_worlds(
        world_roots(source, "world"), target, "world", "vanilla", "paper", "1.21.1"
    )

    assert (target / "world" / "DIM-1" / "level.dat").read_text() == "nether"
    assert (target / "world" / "DIM1" / "level.dat").read_text() == "end"
    assert not (target / "world_nether").exists()


def test_extension_rebuild_classifies_every_supported_target() -> None:
    entries = [
        extension(["paper"]),
        extension(["fabric"]),
        extension(["forge"]),
        extension(["neoforge"]),
        extension(["quilt"]),
        extension([], environment="client"),
    ]
    for target in ("paper", "fabric", "forge", "neoforge", "quilt"):
        reviewed = classify_extensions(entries, "fabric", target)
        assert len(reviewed) == len(entries)
        assert any(item.classification == "compatible_candidate" for item in reviewed)
        assert reviewed[-1].classification == "client_only"


def test_unsafe_level_names_fall_back_to_world() -> None:
    assert safe_level_name("../outside") == "world"
    assert safe_level_name("") == "world"
    assert safe_level_name("family") == "family"


def test_live_discovery_uses_an_unambiguous_world_when_properties_are_stale(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "friends-world"
    (legacy / "region").mkdir(parents=True)
    (legacy / "level.dat").write_bytes(b"world")

    level_name, roots = discover_world_roots(tmp_path, "world")

    assert level_name == "friends-world"
    assert [root.name for root in roots] == ["friends-world"]


def test_live_discovery_blocks_an_empty_configured_world_when_others_are_ambiguous(
    tmp_path: Path,
) -> None:
    (tmp_path / "world").mkdir()
    for name in ("survival", "creative"):
        (tmp_path / name / "region").mkdir(parents=True)
        (tmp_path / name / "level.dat").write_bytes(name.encode())

    level_name, roots = discover_world_roots(tmp_path, "world")

    assert level_name == "world"
    assert roots == ()


def test_modern_paper_target_keeps_the_unified_world_layout(tmp_path: Path) -> None:
    source = tmp_path / "vanilla"
    target = tmp_path / "paper"
    (source / "world" / "DIM-1").mkdir(parents=True)
    (source / "world" / "DIM1").mkdir(parents=True)
    (source / "world" / "level.dat").write_bytes(b"world")
    (source / "world" / "DIM-1" / "region.mca").write_bytes(b"nether")
    (source / "world" / "DIM1" / "region.mca").write_bytes(b"end")
    target.mkdir()
    roots = world_roots(source, "world")

    operations = world_copy_operations(roots, "world", "vanilla", "paper", "26.1")
    copied = copy_worlds(roots, target, "world", "vanilla", "paper", "26.1")

    assert uses_modern_paper_layout("26.1") is True
    assert copied == ["world"]
    assert [operation.destination_relative_path for operation in operations] == ["world"]
    assert (target / "world" / "DIM-1" / "region.mca").read_bytes() == b"nether"
    assert (target / "world" / "DIM1" / "region.mca").read_bytes() == b"end"
    assert not (target / "world_nether").exists()


def test_modern_paper_metadata_is_relocated_only_inside_the_copy(tmp_path: Path) -> None:
    source = tmp_path / "paper"
    target = tmp_path / "fabric"
    metadata = source / "world" / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
    metadata.mkdir(parents=True)
    (source / "world" / "level.dat").write_bytes(b"world")
    (metadata / "weather.dat").write_bytes(b"weather")
    target.mkdir()

    copy_worlds(
        world_roots(source, "world"), target, "world", "paper", "fabric", "26.1"
    )

    assert (target / "world" / "data" / "minecraft" / "weather.dat").read_bytes() == b"weather"
    assert not (
        target
        / "world"
        / "dimensions"
        / "minecraft"
        / "overworld"
        / "data"
        / "minecraft"
        / "weather.dat"
    ).exists()
    assert (metadata / "weather.dat").read_bytes() == b"weather"


def test_review_fingerprint_changes_when_nested_world_data_changes(
    tmp_path: Path,
) -> None:
    world = tmp_path / "world"
    region = world / "region"
    region.mkdir(parents=True)
    chunk = region / "r.0.0.mca"
    chunk.write_bytes(b"before")
    roots = world_roots(tmp_path, "world")
    arguments = {
        "profile_id": "profile",
        "source_distribution": "vanilla",
        "minecraft_version": "1.21.1",
        "target_distribution": "fabric",
        "loader_version": "0.16.10",
        "level_name": "world",
        "roots": roots,
        "entries": [],
        "backup_id": "backup",
    }

    before = review_fingerprint(**arguments)
    chunk.write_bytes(b"after-data")
    after = review_fingerprint(**arguments)

    assert before != after
