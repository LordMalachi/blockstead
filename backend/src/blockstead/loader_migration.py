"""Review and copy world data into a newly provisioned loader profile.

The source profile is never changed. Loader artifacts are provisioned separately
and only Minecraft world roots are copied into the new folder.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from .extensions import ExtensionEntry

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


def _copy_tree(source: Path, destination: Path, *, ignore_dimensions: bool = False) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"The new profile already contains {destination.name}.")
    _assert_no_links(source)
    ignore = (
        (lambda _directory, names: [name for name in names if name in {"DIM-1", "DIM1"}])
        if ignore_dimensions
        else None
    )
    shutil.copytree(source, destination, symlinks=False, ignore=ignore)


def copy_worlds(
    roots: tuple[WorldRoot, ...],
    target: Path,
    level_name: str,
    source_distribution: str,
    target_distribution: str,
) -> list[str]:
    """Copy reviewed worlds, translating Paper's split dimension layout."""

    by_name = {root.name: root.source for root in roots}
    base = by_name.get(level_name)
    if base is None:
        raise ValueError("The reviewed overworld is no longer available.")
    copied: list[str] = []
    if source_distribution != "paper" and target_distribution == "paper":
        _copy_tree(base, target / level_name, ignore_dimensions=True)
        copied.append(level_name)
        for dimension, suffix in (("DIM-1", "_nether"), ("DIM1", "_the_end")):
            source = base / dimension
            if source.is_dir() and not source.is_symlink():
                destination_root = target / f"{level_name}{suffix}"
                destination_root.mkdir(mode=0o755)
                _copy_tree(source, destination_root / dimension)
                copied.append(destination_root.name)
    elif source_distribution == "paper" and target_distribution != "paper":
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
    properties = target / "server.properties"
    properties.write_text(f"level-name={level_name}\n", encoding="utf-8")
    return copied
