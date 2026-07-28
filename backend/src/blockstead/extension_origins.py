"""Trusted catalog provenance for installed extension files.

Jar metadata can identify a mod or plugin, but it cannot prove where Blockstead
obtained the file. This private sidecar is therefore written only after a
checksum-verified catalog install (or an explicitly local import) and is never
treated as publisher authentication for owner-supplied files.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .catalog import PlannedFile
from .extension_ops import ensure_managed_directory
from .extensions import inspect_extension_jar
from .loadout_lockfiles import ExtensionOrigin, OriginMap
from .modrinth import JAR_NAME_PATTERN

ORIGIN_FILE_NAME = ".blockstead-extension-origins.json"
ORIGIN_SCHEMA_VERSION = 1


class OriginRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=5, max_length=132)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sha512: str = Field(pattern=r"^[0-9a-f]{128}$")
    origin: ExtensionOrigin


class OriginRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = ORIGIN_SCHEMA_VERSION
    records: list[OriginRecord] = Field(default_factory=list, max_length=1000)


class OriginRegistryError(ValueError):
    """The private origin registry could not be updated safely."""


def _path(extension_directory: Path) -> Path:
    return ensure_managed_directory(extension_directory) / ORIGIN_FILE_NAME


def _read(extension_directory: Path) -> OriginRegistry:
    path = _path(extension_directory)
    if path.is_symlink():
        raise OriginRegistryError("The extension origin record cannot be a symbolic link.")
    if not path.exists():
        return OriginRegistry()
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            raise OriginRegistryError("The extension origin record is not safe to read.")
        return OriginRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise OriginRegistryError("The extension origin record is invalid.") from exc


def _write(extension_directory: Path, registry: OriginRegistry) -> None:
    directory = ensure_managed_directory(extension_directory)
    target = directory / ORIGIN_FILE_NAME
    staging = directory / f".{ORIGIN_FILE_NAME}.{secrets.token_hex(8)}.part"
    payload = (
        json.dumps(
            registry.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    )
    try:
        with staging.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, target)
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise OriginRegistryError("Blockstead could not save extension origins.") from exc
    finally:
        staging.unlink(missing_ok=True)


def load_origin_map(extension_directory: Path) -> OriginMap:
    """Return only records that still match the installed jar byte-for-byte."""

    if not extension_directory.exists():
        return {}
    registry = _read(extension_directory)
    origins: dict[str, ExtensionOrigin] = {}
    for record in registry.records:
        path = extension_directory / record.file_name
        if not path.is_file() or path.is_symlink():
            disabled = extension_directory.parent / f"{extension_directory.name}-disabled"
            path = disabled / record.file_name
        if not path.is_file() or path.is_symlink():
            continue
        inspected = inspect_extension_jar(path)
        if inspected.sha256 != record.sha256 or inspected.sha512 != record.sha512:
            continue
        origins[record.file_name] = record.origin
    return origins


def record_catalog_files(
    extension_directory: Path,
    source: str,
    planned: Iterable[PlannedFile],
) -> None:
    """Record catalog identity only after the live file matches its published digest."""

    registry = _read(extension_directory)
    by_name = {record.file_name: record for record in registry.records}
    for item in planned:
        path = extension_directory / item.file_name
        if not path.is_file() or path.is_symlink():
            continue
        entry = inspect_extension_jar(path)
        if entry.sha256 is None or entry.sha512 is None:
            continue
        checksum_algorithm = item.checksum_algorithm
        checksum = item.checksum.casefold() if item.checksum else None
        actual = entry.sha256 if checksum_algorithm == "sha256" else entry.sha512
        if (
            checksum_algorithm not in {"sha256", "sha512"}
            or checksum is None
            or actual != checksum
        ):
            continue
        by_name[item.file_name] = OriginRecord(
            file_name=item.file_name,
            sha256=entry.sha256,
            sha512=entry.sha512,
            origin=ExtensionOrigin(
                source=source,
                project_id=item.project_id,
                version_id=item.version_id,
                download_url=item.url,
                checksum_algorithm=checksum_algorithm,
                checksum=checksum,
                verified=True,
            ),
        )
    _write(
        extension_directory,
        OriginRegistry(
            records=sorted(by_name.values(), key=lambda item: item.file_name.casefold())
        ),
    )


def record_local_files(extension_directory: Path, file_names: Iterable[str]) -> None:
    """Record local identity without claiming publisher authenticity."""

    registry = _read(extension_directory)
    by_name = {record.file_name: record for record in registry.records}
    for file_name in file_names:
        if not JAR_NAME_PATTERN.fullmatch(file_name):
            raise OriginRegistryError("The local extension record contains an unsafe name.")
        path = extension_directory / file_name
        entry = inspect_extension_jar(path)
        if entry.sha256 is None or entry.sha512 is None:
            raise OriginRegistryError(f"Blockstead could not checksum {file_name}.")
        by_name[file_name] = OriginRecord(
            file_name=file_name,
            sha256=entry.sha256,
            sha512=entry.sha512,
            origin=ExtensionOrigin(
                source="local",
                checksum_algorithm="sha256",
                checksum=entry.sha256,
                verified=False,
            ),
        )
    _write(
        extension_directory,
        OriginRegistry(
            records=sorted(by_name.values(), key=lambda item: item.file_name.casefold())
        ),
    )


def record_existing_origin(
    extension_directory: Path,
    file_name: str,
    origin: ExtensionOrigin | dict[str, object],
) -> None:
    """Restore a previously trusted origin after a verified jar rollback."""

    if not JAR_NAME_PATTERN.fullmatch(file_name):
        raise OriginRegistryError("The restored extension record contains an unsafe name.")
    parsed = (
        origin
        if isinstance(origin, ExtensionOrigin)
        else ExtensionOrigin.model_validate(origin)
    )
    path = extension_directory / file_name
    entry = inspect_extension_jar(path)
    if entry.sha256 is None or entry.sha512 is None:
        raise OriginRegistryError(f"Blockstead could not checksum {file_name}.")
    registry = _read(extension_directory)
    by_name = {record.file_name: record for record in registry.records}
    by_name[file_name] = OriginRecord(
        file_name=file_name,
        sha256=entry.sha256,
        sha512=entry.sha512,
        origin=parsed,
    )
    _write(
        extension_directory,
        OriginRegistry(
            records=sorted(by_name.values(), key=lambda item: item.file_name.casefold())
        ),
    )


def forget_origin(extension_directory: Path, file_name: str) -> None:
    registry = _read(extension_directory)
    remaining = [record for record in registry.records if record.file_name != file_name]
    if len(remaining) != len(registry.records):
        _write(extension_directory, OriginRegistry(records=remaining))
