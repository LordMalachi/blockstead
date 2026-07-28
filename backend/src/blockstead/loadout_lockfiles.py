"""Reproducible extension loadout lockfiles and read-only import reviews.

The lockfile records what Blockstead can prove from the extension inventory.
Catalog provenance is supplied separately because an inspected jar cannot prove
where it came from. Import review deliberately has no filesystem operations.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .extensions import ExtensionEntry, ExtensionsView

LOCKFILE_SCHEMA_VERSION: Literal[1] = 1
MAX_LOCKFILE_BYTES = 2 * 1024 * 1024

class ExtensionOrigin(BaseModel):
    """Optional, trusted provenance recorded when Blockstead obtained a jar."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(default="unknown", min_length=1, max_length=32)
    project_id: str | None = Field(default=None, max_length=128)
    version_id: str | None = Field(default=None, max_length=128)
    download_url: str | None = Field(default=None, max_length=2048)
    checksum_algorithm: Literal["sha256", "sha512"] | None = None
    checksum: str | None = Field(default=None, max_length=128)
    verified: bool = False

    @field_validator("checksum")
    @classmethod
    def normalize_checksum(cls, value: str | None) -> str | None:
        return value.casefold() if value is not None else None


OriginValue = ExtensionOrigin | Mapping[str, object]
OriginMap = Mapping[str, OriginValue]


class LockedExtension(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: str
    size_bytes: int = Field(ge=0)
    sha256: str | None
    sha512: str | None
    kind: str
    loaders: list[str]
    identifier: str | None
    display_name: str | None
    version: str | None
    minecraft_constraint: str | None
    environment: str | None
    dependencies: list[str]
    readable: bool
    origin: ExtensionOrigin

    @field_validator("sha256")
    @classmethod
    def valid_sha256(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")
        return value

    @field_validator("sha512")
    @classmethod
    def valid_sha512(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) != 128 or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError("sha512 must be a lowercase hexadecimal digest")
        return value


class LoadoutLockfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = LOCKFILE_SCHEMA_VERSION
    generated_at: str
    minecraft_version: str = Field(min_length=1, max_length=64)
    distribution: str = Field(min_length=1, max_length=32)
    loader_version: str | None = Field(default=None, max_length=128)
    installed: list[LockedExtension]
    disabled: list[LockedExtension]

    @field_validator("generated_at")
    @classmethod
    def valid_generated_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("generated_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("generated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def unique_extension_files(self) -> LoadoutLockfile:
        names = [entry.file_name for entry in [*self.installed, *self.disabled]]
        if len(names) != len(set(names)):
            raise ValueError("extension file names must be unique across loadout states")
        return self


class LoadoutMismatch(BaseModel):
    code: str
    message: str
    file_name: str | None = None
    expected: str | None = None
    actual: str | None = None


class LoadoutImportReview(BaseModel):
    valid: bool
    compatible: bool
    lockfile: LoadoutLockfile | None = None
    mismatches: list[LoadoutMismatch] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    mutation_performed: Literal[False] = False


def format_generated_at(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("generated_at must include a timezone")
    return (
        value.astimezone(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def resolve_extension_origin(
    entry: ExtensionEntry, origins: OriginMap | None
) -> ExtensionOrigin:
    if origins:
        for key in (entry.sha512, entry.sha256, entry.identifier, entry.file_name):
            if key is not None and key in origins:
                value = origins[key]
                if isinstance(value, ExtensionOrigin):
                    return value
                return ExtensionOrigin.model_validate(value)
    return ExtensionOrigin()


def _locked(entry: ExtensionEntry, origins: OriginMap | None) -> LockedExtension:
    payload = entry.model_dump()
    payload["loaders"] = sorted(set(entry.loaders))
    payload["dependencies"] = sorted(set(entry.dependencies), key=str.casefold)
    return LockedExtension(
        **payload,
        origin=resolve_extension_origin(entry, origins),
    )


def _entry_key(entry: LockedExtension) -> tuple[str, str, str]:
    return (
        (entry.identifier or "").casefold(),
        entry.file_name.casefold(),
        entry.sha256 or "",
    )


def build_loadout_lockfile(
    view: ExtensionsView,
    *,
    minecraft_version: str,
    distribution: str,
    loader_version: str | None,
    generated_at: datetime,
    origins: OriginMap | None = None,
) -> LoadoutLockfile:
    """Build a stable model from a previously read ``ExtensionsView``."""

    installed = sorted((_locked(entry, origins) for entry in view.entries), key=_entry_key)
    disabled = sorted(
        (_locked(entry, origins) for entry in view.disabled_entries), key=_entry_key
    )
    return LoadoutLockfile(
        generated_at=format_generated_at(generated_at),
        minecraft_version=minecraft_version,
        distribution=distribution,
        loader_version=loader_version,
        installed=installed,
        disabled=disabled,
    )


def serialize_loadout_lockfile(lockfile: LoadoutLockfile) -> bytes:
    """Return canonical UTF-8 JSON suitable for download or hashing."""

    payload = lockfile.model_dump(mode="json")
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )


def _state_map(lockfile: LoadoutLockfile) -> dict[str, tuple[str, LockedExtension]]:
    result: dict[str, tuple[str, LockedExtension]] = {}
    for state, entries in (("installed", lockfile.installed), ("disabled", lockfile.disabled)):
        for entry in entries:
            result[entry.file_name] = (state, entry)
    return result


def _fingerprint(entry: LockedExtension) -> tuple[object, ...]:
    return (
        entry.sha256,
        entry.sha512,
        entry.size_bytes,
        entry.kind,
        tuple(entry.loaders),
        entry.identifier,
        entry.version,
        entry.minecraft_constraint,
        entry.environment,
        tuple(entry.dependencies),
        entry.readable,
        entry.origin.model_dump_json(),
    )


def _context_mismatches(
    expected: LoadoutLockfile, actual: LoadoutLockfile
) -> list[LoadoutMismatch]:
    mismatches: list[LoadoutMismatch] = []
    for field, code, label in (
        ("minecraft_version", "minecraft_version", "Minecraft version"),
        ("distribution", "distribution", "server distribution"),
        ("loader_version", "loader_version", "loader version"),
    ):
        wanted = getattr(expected, field)
        found = getattr(actual, field)
        if wanted != found:
            mismatches.append(
                LoadoutMismatch(
                    code=f"{code}_mismatch",
                    message=f"The lockfile {label} does not match this profile.",
                    expected=str(wanted) if wanted is not None else None,
                    actual=str(found) if found is not None else None,
                )
            )
    return mismatches


def _extension_mismatches(
    expected: LoadoutLockfile, actual: LoadoutLockfile
) -> list[LoadoutMismatch]:
    mismatches: list[LoadoutMismatch] = []
    wanted = _state_map(expected)
    found = _state_map(actual)
    found_by_sha = {
        entry.sha256: (name, state, entry)
        for name, (state, entry) in found.items()
        if entry.sha256
    }
    matched_actual: set[str] = set()
    for name, (expected_state, expected_entry) in wanted.items():
        current = found.get(name)
        if current is None and expected_entry.sha256:
            renamed = found_by_sha.get(expected_entry.sha256)
            if renamed is not None:
                actual_name, actual_state, actual_entry = renamed
                matched_actual.add(actual_name)
                mismatches.append(
                    LoadoutMismatch(
                        code="file_name_mismatch",
                        file_name=name,
                        message="The same extension checksum is present under another file name.",
                        expected=name,
                        actual=actual_name,
                    )
                )
                current = (actual_state, actual_entry)
        if current is None:
            mismatches.append(
                LoadoutMismatch(
                    code="missing_extension",
                    file_name=name,
                    message="An extension recorded by the lockfile is not present.",
                    expected=expected_state,
                    actual="missing",
                )
            )
            continue
        actual_state, actual_entry = current
        matched_actual.add(actual_entry.file_name)
        if expected_state != actual_state:
            mismatches.append(
                LoadoutMismatch(
                    code="extension_state_mismatch",
                    file_name=name,
                    message="The extension enabled/disabled state differs from the lockfile.",
                    expected=expected_state,
                    actual=actual_state,
                )
            )
        if expected_entry.sha256 != actual_entry.sha256:
            mismatches.append(
                LoadoutMismatch(
                    code="extension_checksum_mismatch",
                    file_name=name,
                    message="The installed file checksum differs from the lockfile.",
                    expected=expected_entry.sha256,
                    actual=actual_entry.sha256,
                )
            )
        elif _fingerprint(expected_entry) != _fingerprint(actual_entry):
            mismatches.append(
                LoadoutMismatch(
                    code="extension_metadata_mismatch",
                    file_name=name,
                    message="The extension metadata or recorded origin differs from the lockfile.",
                )
            )
    for name, (state, _entry) in found.items():
        if name not in matched_actual:
            mismatches.append(
                LoadoutMismatch(
                    code="extra_extension",
                    file_name=name,
                    message="This profile contains an extension not recorded by the lockfile.",
                    expected="absent",
                    actual=state,
                )
            )
    return mismatches


def review_loadout_lockfile(
    data: bytes | str,
    current_view: ExtensionsView,
    *,
    minecraft_version: str,
    distribution: str,
    loader_version: str | None,
    origins: OriginMap | None = None,
) -> LoadoutImportReview:
    """Validate and compare a lockfile without changing the current loadout."""

    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_LOCKFILE_BYTES:
        return LoadoutImportReview(
            valid=False,
            compatible=False,
            blockers=["The loadout lockfile is larger than Blockstead accepts."],
        )
    try:
        expected = LoadoutLockfile.model_validate_json(raw)
    except ValidationError:
        return LoadoutImportReview(
            valid=False,
            compatible=False,
            blockers=["The loadout lockfile is invalid or uses an unsupported schema."],
        )
    current = build_loadout_lockfile(
        current_view,
        minecraft_version=minecraft_version,
        distribution=distribution,
        loader_version=loader_version,
        generated_at=datetime.fromisoformat(expected.generated_at.replace("Z", "+00:00")),
        origins=origins,
    )
    mismatches = [
        *_context_mismatches(expected, current),
        *_extension_mismatches(expected, current),
    ]
    return LoadoutImportReview(
        valid=True,
        compatible=not mismatches,
        lockfile=expected,
        mismatches=mismatches,
    )
