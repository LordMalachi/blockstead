"""Build safe, client-facing Modrinth packs from an extension inventory."""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from .extensions import ExtensionEntry, ExtensionsView
from .loadout_lockfiles import (
    ExtensionOrigin,
    OriginMap,
    format_generated_at,
    resolve_extension_origin,
)

PLAYER_PACK_SCHEMA_VERSION = 1
_LOADER_DEPENDENCIES = {
    "fabric": "fabric-loader",
    "forge": "forge",
    "neoforge": "neoforge",
    "quilt": "quilt-loader",
}
_SERVER_ENVIRONMENTS = frozenset({"server", "dedicated_server", "server-only"})
_CLIENT_ENVIRONMENTS = frozenset({"client", "client-only"})
_UNIVERSAL_ENVIRONMENTS = frozenset({"*", "both", "universal"})


class PlayerPackIncludedFile(BaseModel):
    file_name: str
    path: str
    identifier: str | None
    version: str | None
    source: str
    project_id: str | None
    version_id: str | None


class PlayerPackManualRequirement(BaseModel):
    file_name: str
    identifier: str | None
    version: str | None
    sha256: str | None
    reason: str


class PlayerPackDisclosure(BaseModel):
    code: str
    file_name: str
    message: str


class PlayerPackExcludedFile(BaseModel):
    file_name: str
    reason: str


class PlayerPackExportSummary(BaseModel):
    schema_version: int = PLAYER_PACK_SCHEMA_VERSION
    generated_at: str
    file_name: str
    included: list[PlayerPackIncludedFile] = Field(default_factory=list)
    manual_requirements: list[PlayerPackManualRequirement] = Field(default_factory=list)
    disclosures: list[PlayerPackDisclosure] = Field(default_factory=list)
    excluded: list[PlayerPackExcludedFile] = Field(default_factory=list)


@dataclass(frozen=True)
class PlayerPackExportResult:
    """Archive bytes plus API-friendly review details."""

    archive: bytes
    index: dict[str, object]
    summary: PlayerPackExportSummary


class PlayerPackExportError(ValueError):
    """The requested player pack cannot be represented safely."""


def _safe_pack_text(value: str, field: str, maximum: int) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum or any(char in cleaned for char in "\r\n\x00"):
        raise PlayerPackExportError(f"The player pack {field} is not usable.")
    return cleaned


def _archive_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return f"{(slug or 'blockstead-player-pack')[:80]}.mrpack"


def _known_server_only(entry: ExtensionEntry) -> bool:
    environment = (entry.environment or "").casefold()
    return entry.kind == "paper-plugin" or environment in _SERVER_ENVIRONMENTS


def _environment(entry: ExtensionEntry) -> str:
    environment = (entry.environment or "").casefold()
    if environment in _CLIENT_ENVIRONMENTS:
        return "client"
    if environment in _UNIVERSAL_ENVIRONMENTS:
        return "universal"
    if _known_server_only(entry):
        return "server"
    return "unknown"


def _verified_download(entry: ExtensionEntry, origin: ExtensionOrigin) -> str | None:
    if (
        not origin.verified
        or origin.source != "modrinth"
        or not origin.download_url
        or not origin.checksum_algorithm
        or not origin.checksum
    ):
        return None
    parsed = urlparse(origin.download_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    actual = entry.sha256 if origin.checksum_algorithm == "sha256" else entry.sha512
    if actual is None or actual.casefold() != origin.checksum.casefold():
        return None
    return origin.download_url


def _manual_requirement(
    entry: ExtensionEntry, reason: str
) -> PlayerPackManualRequirement:
    return PlayerPackManualRequirement(
        file_name=entry.file_name,
        identifier=entry.identifier,
        version=entry.version,
        sha256=entry.sha256,
        reason=reason,
    )


def _zip_member(name: str, data: bytes) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info, data


def build_player_mrpack(
    view: ExtensionsView,
    *,
    minecraft_version: str,
    distribution: str,
    loader_version: str | None,
    pack_name: str,
    version_id: str,
    summary: str,
    generated_at: datetime,
    origins: OriginMap | None = None,
) -> PlayerPackExportResult:
    """Create a deterministic `.mrpack` without embedding any extension jars."""

    name = _safe_pack_text(pack_name, "name", 120)
    version = _safe_pack_text(version_id, "version", 64)
    description = _safe_pack_text(summary, "summary", 500)
    if distribution in _LOADER_DEPENDENCIES and not loader_version:
        raise PlayerPackExportError("A loader version is required for this player pack.")

    included: list[PlayerPackIncludedFile] = []
    manual: list[PlayerPackManualRequirement] = []
    disclosures: list[PlayerPackDisclosure] = []
    excluded: list[PlayerPackExcludedFile] = []
    index_files: list[dict[str, object]] = []

    for entry in sorted(view.entries, key=lambda item: item.file_name.casefold()):
        environment = _environment(entry)
        origin = resolve_extension_origin(entry, origins)
        if environment == "server":
            excluded.append(
                PlayerPackExcludedFile(
                    file_name=entry.file_name,
                    reason="Known server-only extension; players do not need it.",
                )
            )
            continue
        if environment == "unknown":
            disclosures.append(
                PlayerPackDisclosure(
                    code="unknown_environment",
                    file_name=entry.file_name,
                    message=(
                        "The jar does not declare whether players need it, so Blockstead "
                        "did not guess or add it to the downloadable pack."
                    ),
                )
            )
            if origin.source in {"unknown", "manual", "local"}:
                manual.append(
                    _manual_requirement(
                        entry,
                        "Locally supplied jar with unknown client/server environment; "
                        "review and provide it manually if players need it.",
                    )
                )
            continue

        download = _verified_download(entry, origin)
        if download is None or entry.sha512 is None:
            if origin.source in {"unknown", "manual", "local"}:
                reason = "Locally supplied jars cannot be embedded or uploaded by Blockstead."
            elif origin.source != "modrinth":
                reason = (
                    "This catalog source was not marked safe for automatic player-pack "
                    "redistribution."
                )
            else:
                reason = "The recorded catalog download could not be verified against this jar."
            manual.append(_manual_requirement(entry, reason))
            if origin.source not in {"unknown", "manual", "local"}:
                disclosures.append(
                    PlayerPackDisclosure(
                        code="unverified_download_source",
                        file_name=entry.file_name,
                        message=reason,
                    )
                )
            continue

        path = str(PurePosixPath("mods") / entry.file_name)
        env = (
            {"client": "required", "server": "unsupported"}
            if environment == "client"
            else {"client": "required", "server": "required"}
        )
        index_files.append(
            {
                "path": path,
                "hashes": {"sha512": entry.sha512},
                "env": env,
                "downloads": [download],
                "fileSize": entry.size_bytes,
            }
        )
        included.append(
            PlayerPackIncludedFile(
                file_name=entry.file_name,
                path=path,
                identifier=entry.identifier,
                version=entry.version,
                source=origin.source,
                project_id=origin.project_id,
                version_id=origin.version_id,
            )
        )

    dependencies: dict[str, str] = {"minecraft": minecraft_version}
    loader_key = _LOADER_DEPENDENCIES.get(distribution)
    if loader_key and loader_version:
        dependencies[loader_key] = loader_version
    index: dict[str, object] = {
        "formatVersion": 1,
        "game": "minecraft",
        "name": name,
        "versionId": version,
        "summary": description,
        "files": index_files,
        "dependencies": dependencies,
    }
    output_name = _archive_name(name)
    exported_at = format_generated_at(generated_at)
    export_manifest = {
        "schemaVersion": PLAYER_PACK_SCHEMA_VERSION,
        "generatedAt": exported_at,
        "manualRequirements": [
            requirement.model_dump(mode="json") for requirement in manual
        ],
        "disclosures": [item.model_dump(mode="json") for item in disclosures],
        "excluded": [item.model_dump(mode="json") for item in excluded],
        "notice": (
            "This archive contains references to verified downloads only. "
            "It never embeds or uploads locally supplied jars."
        ),
    }
    index_bytes = json.dumps(
        index, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest_bytes = json.dumps(
        export_manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for member, content in (
            _zip_member("modrinth.index.json", index_bytes),
            _zip_member("blockstead.export.json", manifest_bytes),
        ):
            archive.writestr(member, content)
    export_summary = PlayerPackExportSummary(
        generated_at=exported_at,
        file_name=output_name,
        included=included,
        manual_requirements=manual,
        disclosures=disclosures,
        excluded=excluded,
    )
    return PlayerPackExportResult(
        archive=buffer.getvalue(),
        index=index,
        summary=export_summary,
    )
