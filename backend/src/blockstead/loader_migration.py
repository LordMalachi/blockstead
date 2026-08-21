"""Review and copy world data into a newly provisioned loader profile.

The source profile is never changed. Loader artifacts are provisioned separately
and only Minecraft world roots are copied into the new folder.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .extensions import ExtensionEntry
from .host_fs import atomic_write_text

TARGET_DISTRIBUTIONS = frozenset({"paper", "fabric", "forge", "quilt", "neoforge"})


class MigrationReviewRequest(BaseModel):
    target_distribution: str = Field(pattern=r"^(paper|fabric|forge|quilt|neoforge)$")


class MigrationApplyRequest(MigrationReviewRequest):
    review_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    backup_id: str = Field(min_length=1, max_length=36)
    name: str = Field(min_length=1, max_length=80)
    directory_name: str = Field(
        min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$"
    )
    loader_version: str | None = Field(
        default=None, max_length=64, pattern=r"^[0-9A-Za-z][0-9A-Za-z.+_-]*$"
    )
    acknowledge_modded_world: bool = False

    @field_validator("name")
    @classmethod
    def usable_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The new profile name cannot be blank.")
        return value


class MigrationExtension(BaseModel):
    file_name: str
    name: str
    version: str | None
    identifier: str | None
    source_kind: str
    classification: str
    detail: str


@dataclass(frozen=True)
class WorldRoot:
    name: str
    source: Path


@dataclass(frozen=True)
class WorldCopyOperation:
    """One owner-visible source/destination pair in a migration plan."""

    source_path: str
    destination_relative_path: str
    detail: str


_MODERN_PAPER_METADATA = (
    "game_rules.dat",
    "scheduled_events.dat",
    "wandering_trader.dat",
    "weather.dat",
    "world_gen_settings.dat",
)


def _has_world_evidence(path: Path) -> bool:
    return (
        (path / "level.dat").is_file()
        or (path / "region").is_dir()
        or (path / "DIM-1").is_dir()
        or (path / "DIM1").is_dir()
    )


def safe_level_name(value: str | None) -> str:
    name = (value or "world").strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or name.startswith(".")
    ):
        return "world"
    return name


def world_roots(directory: Path, level_name: str) -> tuple[WorldRoot, ...]:
    names = (level_name, f"{level_name}_nether", f"{level_name}_the_end")
    return tuple(
        WorldRoot(name=name, source=directory / name)
        for name in names
        if (directory / name).is_dir() and not (directory / name).is_symlink()
    )


def discover_world_roots(
    directory: Path, configured_level_name: str
) -> tuple[str, tuple[WorldRoot, ...]]:
    """Locate a generated world even when server.properties is stale.

    The configured name remains authoritative when it points to a directory
    that looks like a Minecraft world. Otherwise, accept one unambiguous
    top-level world-shaped directory. This is read-only and never follows
    links, so a refresh cannot broaden the migration's file access.
    """

    configured = safe_level_name(configured_level_name)
    configured_root = directory / configured
    if (
        configured_root.is_dir()
        and not configured_root.is_symlink()
        and _has_world_evidence(configured_root)
    ):
        return configured, world_roots(directory, configured)
    try:
        candidates = sorted(
            (
                entry
                for entry in directory.iterdir()
                if entry.is_dir()
                and not entry.is_symlink()
                and not entry.name.endswith(("_nether", "_the_end"))
                and _has_world_evidence(entry)
            ),
            key=lambda entry: entry.name,
        )
    except OSError:
        candidates = []
    if len(candidates) == 1:
        level_name = candidates[0].name
        return level_name, world_roots(directory, level_name)
    # Preserve the configured name and its ordinary roots when discovery is
    # ambiguous, but return no roots. An empty configured folder or an orphaned
    # Paper dimension folder is not enough evidence to approve a migration.
    return configured, ()


def uses_modern_paper_layout(minecraft_version: str) -> bool:
    """Paper 26.1+ uses the unified Vanilla-like world layout."""

    match = re.match(r"^(\d+)(?:\.(\d+))?", minecraft_version)
    if match is None:
        return False
    version = (int(match.group(1)), int(match.group(2) or 0))
    return version >= (26, 1)


def world_copy_operations(
    roots: tuple[WorldRoot, ...],
    level_name: str,
    source_distribution: str,
    target_distribution: str,
    minecraft_version: str,
) -> tuple[WorldCopyOperation, ...]:
    """Describe the actual loader-aware paths copied into the new server."""

    by_name = {root.name: root.source for root in roots}
    base = by_name.get(level_name)
    if base is None:
        return ()
    operations: list[WorldCopyOperation] = []
    modern_paper = uses_modern_paper_layout(minecraft_version)
    split_paper = any(
        name in by_name for name in (f"{level_name}_nether", f"{level_name}_the_end")
    )
    if source_distribution == "paper" and target_distribution != "paper" and split_paper:
        operations.append(
            WorldCopyOperation(str(base), level_name, "Overworld and shared world data")
        )
        for source_name, dimension, label in (
            (f"{level_name}_nether", "DIM-1", "Nether dimension data"),
            (f"{level_name}_the_end", "DIM1", "End dimension data"),
        ):
            source_root = by_name.get(source_name)
            dimension_source = source_root / dimension if source_root is not None else None
            if (
                dimension_source is not None
                and dimension_source.is_dir()
                and not dimension_source.is_symlink()
            ):
                operations.append(
                    WorldCopyOperation(
                        str(dimension_source), f"{level_name}/{dimension}", label
                    )
                )
    else:
        operations.extend(
            WorldCopyOperation(str(root.source), root.name, "Complete world folder")
            for root in roots
        )
    if source_distribution == "paper" and target_distribution != "paper" and modern_paper:
        metadata = base / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
        for name in _MODERN_PAPER_METADATA:
            source = metadata / name
            if source.is_file() and not source.is_symlink():
                operations.append(
                    WorldCopyOperation(
                        str(source),
                        f"{level_name}/data/minecraft/{name}",
                        "Paper metadata moved inside the new copy for Vanilla-compatible loaders.",
                    )
                )
    return tuple(operations)


def classify_extensions(
    entries: list[ExtensionEntry], source_distribution: str, target_distribution: str
) -> list[MigrationExtension]:
    target_loaders = (
        {"paper"}
        if target_distribution == "paper"
        else {target_distribution, *(["fabric"] if target_distribution == "quilt" else [])}
    )
    result: list[MigrationExtension] = []
    for entry in entries:
        declared = set(entry.loaders)
        if entry.environment == "client":
            classification = "client_only"
            detail = "Client-only; do not install it on the new server."
        elif declared and declared & target_loaders:
            classification = "compatible_candidate"
            detail = (
                "This project declares the target loader. Reinstall a compatible release "
                "through the target profile's catalog."
            )
        elif entry.identifier:
            classification = "replacement_needed"
            detail = (
                "This file is for the old loader. Search for a target-loader release or "
                "replacement before starting the migrated world."
            )
        else:
            classification = "unknown"
            detail = (
                "Blockstead could not identify this file. Review it manually; it was not copied."
            )
        result.append(
            MigrationExtension(
                file_name=entry.file_name,
                name=entry.display_name or entry.file_name,
                version=entry.version,
                identifier=entry.identifier,
                source_kind=entry.kind,
                classification=classification,
                detail=detail,
            )
        )
    return result


def review_fingerprint(
    *,
    profile_id: str,
    source_distribution: str,
    minecraft_version: str,
    target_distribution: str,
    loader_version: str | None,
    level_name: str,
    roots: tuple[WorldRoot, ...],
    entries: list[ExtensionEntry],
    backup_id: str | None,
) -> str:
    def tree_fingerprint(root: WorldRoot) -> str:
        digest = hashlib.sha256()
        paths = sorted(
            root.source.rglob("*"),
            key=lambda item: str(item.relative_to(root.source)),
        )
        for path in paths:
            relative = str(path.relative_to(root.source))
            try:
                details = path.lstat()
            except OSError:
                digest.update(f"missing:{relative}\n".encode())
                continue
            kind = "link" if path.is_symlink() else "directory" if path.is_dir() else "file"
            digest.update(
                f"{kind}:{relative}:{details.st_size}:{details.st_mtime_ns}\n".encode()
            )
        return digest.hexdigest()

    evidence = {
        "profile_id": profile_id,
        "source_distribution": source_distribution,
        "minecraft_version": minecraft_version,
        "target_distribution": target_distribution,
        "loader_version": loader_version,
        "level_name": level_name,
        "roots": [
            {
                "name": root.name,
                "mtime": root.source.stat().st_mtime_ns,
                "tree": tree_fingerprint(root),
            }
            for root in roots
        ],
        "extensions": [
            [entry.file_name, entry.sha256, entry.kind]
            for entry in sorted(entries, key=lambda item: item.file_name)
        ],
        "backup_id": backup_id,
    }
    digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return digest[:16]


def _assert_no_links(root: Path) -> None:
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError(f"{root.name} contains a symbolic link and cannot be migrated safely.")


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"The new profile already contains {destination.name}.")
    _assert_no_links(source)
    shutil.copytree(source, destination, symlinks=False)


def _move_modern_paper_metadata(destination_base: Path) -> None:
    source_root = (
        destination_base / "dimensions" / "minecraft" / "overworld" / "data" / "minecraft"
    )
    destination_root = destination_base / "data" / "minecraft"
    for name in _MODERN_PAPER_METADATA:
        source = source_root / name
        if not source.is_file() or source.is_symlink():
            continue
        destination_root.mkdir(parents=True, exist_ok=True)
        source.replace(destination_root / name)


def _write_level_name(properties: Path, level_name: str) -> None:
    """Set level-name without discarding properties an installer may have created."""

    try:
        lines = properties.read_text(encoding="utf-8").splitlines() if properties.is_file() else []
    except OSError as exc:
        raise ValueError("The new server properties could not be read.") from exc
    replacement = f"level-name={level_name}"
    updated: list[str] = []
    replaced = False
    for line in lines:
        key, separator, _value = line.partition("=")
        if separator and key.strip() == "level-name":
            if not replaced:
                updated.append(replacement)
                replaced = True
            continue
        updated.append(line)
    if not replaced:
        updated.append(replacement)
    try:
        atomic_write_text(properties, "\n".join(updated) + "\n")
    except OSError as exc:
        raise ValueError("The new server properties could not be written.") from exc


def copy_worlds(
    roots: tuple[WorldRoot, ...],
    target: Path,
    level_name: str,
    source_distribution: str,
    target_distribution: str,
    minecraft_version: str,
) -> list[str]:
    """Copy reviewed worlds, translating the Paper layout for this game version."""

    by_name = {root.name: root.source for root in roots}
    base = by_name.get(level_name)
    if base is None:
        raise ValueError("The reviewed overworld is no longer available.")
    copied: list[str] = []
    modern_paper = uses_modern_paper_layout(minecraft_version)
    split_paper = any(
        name in by_name for name in (f"{level_name}_nether", f"{level_name}_the_end")
    )
    if source_distribution == "paper" and target_distribution != "paper" and split_paper:
        _copy_tree(base, target / level_name)
        copied.append(level_name)
        destination_base = target / level_name
        for source_name, dimension in (
            (f"{level_name}_nether", "DIM-1"),
            (f"{level_name}_the_end", "DIM1"),
        ):
            source_root = by_name.get(source_name)
            if source_root is None:
                continue
            source_dimension = source_root / dimension
            if source_dimension.is_dir() and not source_dimension.is_symlink():
                _copy_tree(source_dimension, destination_base / dimension)
                copied.append(source_name)
    else:
        for root in roots:
            _copy_tree(root.source, target / root.name)
            copied.append(root.name)
    if source_distribution == "paper" and target_distribution != "paper" and modern_paper:
        _move_modern_paper_metadata(target / level_name)
    _write_level_name(target / "server.properties", level_name)
    return copied
