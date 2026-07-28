from pathlib import Path

from blockstead.extensions import ExtensionEntry
from blockstead.loader_migration import (
    classify_extensions,
    copy_worlds,
    review_fingerprint,
    safe_level_name,
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

    copied = copy_worlds(roots, target, "family", "paper", "paper")

    assert copied == ["family", "family_nether", "family_the_end"]
    assert (target / "family" / "level.dat").read_text(encoding="utf-8") == "family"
    assert (target / "server.properties").read_text(encoding="utf-8") == "level-name=family\n"
    assert (source / "family" / "level.dat").read_text(encoding="utf-8") == "family"


def test_paper_dimensions_are_merged_for_mod_loaders(tmp_path: Path) -> None:
    source = tmp_path / "paper"
    target = tmp_path / "fabric"
    (source / "world").mkdir(parents=True)
    (source / "world_nether" / "DIM-1").mkdir(parents=True)
    (source / "world_the_end" / "DIM1").mkdir(parents=True)
    (source / "world_nether" / "DIM-1" / "level.dat").write_text("nether")
    (source / "world_the_end" / "DIM1" / "level.dat").write_text("end")
    target.mkdir()

    copy_worlds(world_roots(source, "world"), target, "world", "paper", "fabric")

    assert (target / "world" / "DIM-1" / "level.dat").read_text() == "nether"
    assert (target / "world" / "DIM1" / "level.dat").read_text() == "end"
    assert not (target / "world_nether").exists()


def test_vanilla_dimensions_are_split_for_paper(tmp_path: Path) -> None:
    source = tmp_path / "vanilla"
    target = tmp_path / "paper"
    (source / "world" / "DIM-1").mkdir(parents=True)
    (source / "world" / "DIM1").mkdir(parents=True)
    (source / "world" / "DIM-1" / "level.dat").write_text("nether")
    (source / "world" / "DIM1" / "level.dat").write_text("end")
    target.mkdir()

    copy_worlds(world_roots(source, "world"), target, "world", "vanilla", "paper")

    assert (target / "world_nether" / "DIM-1" / "level.dat").read_text() == "nether"
    assert (target / "world_the_end" / "DIM1" / "level.dat").read_text() == "end"
    assert not (target / "world" / "DIM-1").exists()


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
