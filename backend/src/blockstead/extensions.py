"""Read-only inventory of plugin and mod jars.

Jars are opened as archives to read declared metadata only; nothing is
ever executed, moved, or rewritten. Warnings are advisory: metadata can
prove some incompatibilities, but it can never prove compatibility.
"""

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

try:  # Python 3.11+ standard library
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - older development interpreters
    import tomli as tomllib  # type: ignore[no-redef]

from .distributions import DISTRIBUTIONS

MAX_JARS = 200
MAX_METADATA_BYTES = 1_000_000

Kind = Literal[
    "paper-plugin", "fabric-mod", "quilt-mod", "neoforge-mod", "forge-mod", "unknown"
]

_NATIVE_LOADERS: dict[str, frozenset[str]] = {
    "paper": frozenset({"paper"}),
    "fabric": frozenset({"fabric"}),
    "quilt": frozenset({"quilt", "fabric"}),
    "forge": frozenset({"forge"}),
    "neoforge": frozenset({"neoforge"}),
}


class ExtensionEntry(BaseModel):
    file_name: str
    size_bytes: int
    sha256: str | None
    kind: Kind
    loaders: list[str]
    identifier: str | None
    display_name: str | None
    version: str | None
    minecraft_constraint: str | None
    environment: str | None
    dependencies: list[str]
    readable: bool


class ExtensionWarning(BaseModel):
    code: str
    message: str
    files: list[str]


class ExtensionsView(BaseModel):
    directory: str | None
    present: bool
    entries: list[ExtensionEntry]
    disabled_entries: list[ExtensionEntry] = []
    warnings: list[ExtensionWarning]
    truncated: bool


@dataclass
class _Metadata:
    loaders: list[str] = field(default_factory=list)
    identifier: str | None = None
    display_name: str | None = None
    version: str | None = None
    minecraft_constraint: str | None = None
    environment: str | None = None
    dependencies: list[str] = field(default_factory=list)

    def fill(self, attribute: str, value: str | None) -> None:
        """Record a value only when nothing earlier already claimed the field."""
        if getattr(self, attribute) is None and value is not None:
            setattr(self, attribute, value)


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_METADATA_BYTES:
        return None
    try:
        return archive.read(name)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return None


def _clean(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith("${"):
        return None
    return text[:200]


def _parse_fabric(raw: bytes, found: _Metadata) -> None:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    found.loaders.append("fabric")
    found.fill("identifier", _clean(data.get("id")))
    found.fill("display_name", _clean(data.get("name")))
    found.fill("version", _clean(data.get("version")))
    found.fill("environment", _clean(data.get("environment")))
    depends = data.get("depends")
    if isinstance(depends, dict):
        found.fill("minecraft_constraint", _clean(depends.get("minecraft")))
        if not found.dependencies:
            found.dependencies = sorted(
                str(key)[:100] for key in depends if key not in {"minecraft", "java"}
            )


def _parse_quilt(raw: bytes, found: _Metadata) -> None:
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    loader = data.get("quilt_loader")
    if not isinstance(loader, dict):
        return
    found.loaders.append("quilt")
    found.fill("identifier", _clean(loader.get("id")))
    metadata = loader.get("metadata")
    if isinstance(metadata, dict):
        found.fill("display_name", _clean(metadata.get("name")))
    found.fill("version", _clean(loader.get("version")))
    depends = loader.get("depends")
    records = depends if isinstance(depends, list) else []
    declared: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        dep_id = record.get("id")
        versions = record.get("versions")
        constraint = versions[0] if isinstance(versions, list) and versions else versions
        if dep_id == "minecraft":
            found.fill("minecraft_constraint", _clean(constraint))
        elif isinstance(dep_id, str) and dep_id not in {"java", "quilt_loader"}:
            declared.append(dep_id[:100])
    if declared and not found.dependencies:
        found.dependencies = sorted(declared)


def _parse_mods_toml(raw: bytes, loader: str, found: _Metadata) -> None:
    try:
        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, ValueError):
        return
    mods = data.get("mods")
    first = mods[0] if isinstance(mods, list) and mods and isinstance(mods[0], dict) else {}
    found.loaders.append(loader)
    found.fill("identifier", _clean(first.get("modId")))
    found.fill("display_name", _clean(first.get("displayName")))
    found.fill("version", _clean(first.get("version")))
    mod_id = first.get("modId")
    dependencies = data.get("dependencies")
    declared: list[str] = []
    records = (
        dependencies.get(mod_id)
        if isinstance(dependencies, dict) and isinstance(mod_id, str)
        else None
    )
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        dep_id = record.get("modId")
        if dep_id == "minecraft":
            found.fill("minecraft_constraint", _clean(record.get("versionRange")))
        elif isinstance(dep_id, str) and dep_id != loader:
            declared.append(dep_id[:100])
    if declared and not found.dependencies:
        found.dependencies = sorted(declared)


def _parse_plugin_yml(raw: bytes, found: _Metadata) -> None:
    try:
        data = yaml.safe_load(raw.decode("utf-8", errors="replace"))
    except yaml.YAMLError:
        return
    if not isinstance(data, dict):
        return
    found.loaders.append("paper")
    found.fill("identifier", _clean(data.get("name")))
    found.fill("display_name", _clean(data.get("name")))
    version = data.get("version")
    found.fill("version", _clean(str(version)) if version is not None else None)
    api = data.get("api-version")
    found.fill("minecraft_constraint", _clean(str(api)) if api is not None else None)
    depend = data.get("depend")
    if isinstance(depend, list) and not found.dependencies:
        found.dependencies = sorted(str(item)[:100] for item in depend if isinstance(item, str))


def _kind_of(loaders: list[str]) -> Kind:
    for loader, kind in (
        ("quilt", "quilt-mod"),
        ("fabric", "fabric-mod"),
        ("neoforge", "neoforge-mod"),
        ("forge", "forge-mod"),
        ("paper", "paper-plugin"),
    ):
        if loader in loaders:
            return kind  # type: ignore[return-value]
    return "unknown"


def _inspect_jar(path: Path) -> ExtensionEntry:
    found = _Metadata()
    sha256: str | None = None
    readable = False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        sha256 = digest.hexdigest()
        with zipfile.ZipFile(path) as archive:
            fabric = _read_member(archive, "fabric.mod.json")
            if fabric is not None:
                _parse_fabric(fabric, found)
            quilt = _read_member(archive, "quilt.mod.json")
            if quilt is not None:
                _parse_quilt(quilt, found)
            neo = _read_member(archive, "META-INF/neoforge.mods.toml")
            if neo is not None:
                _parse_mods_toml(neo, "neoforge", found)
            forge = _read_member(archive, "META-INF/mods.toml")
            if forge is not None:
                _parse_mods_toml(forge, "forge", found)
            plugin = _read_member(archive, "paper-plugin.yml") or _read_member(
                archive, "plugin.yml"
            )
            if plugin is not None:
                _parse_plugin_yml(plugin, found)
        readable = True
    except (OSError, zipfile.BadZipFile):
        pass
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return ExtensionEntry(
        file_name=path.name,
        size_bytes=size,
        sha256=sha256,
        kind=_kind_of(found.loaders) if readable else "unknown",
        loaders=found.loaders,
        identifier=found.identifier,
        display_name=found.display_name,
        version=found.version,
        minecraft_constraint=found.minecraft_constraint,
        environment=found.environment,
        dependencies=found.dependencies,
        readable=readable,
    )


def _collect_warnings(distribution: str, entries: list[ExtensionEntry]) -> list[ExtensionWarning]:
    warnings: list[ExtensionWarning] = []
    native = _NATIVE_LOADERS.get(distribution, frozenset())
    by_identifier: dict[str, list[str]] = {}
    for entry in entries:
        if entry.identifier:
            by_identifier.setdefault(entry.identifier, []).append(entry.file_name)
    for identifier, files in sorted(by_identifier.items()):
        if len(files) > 1:
            warnings.append(
                ExtensionWarning(
                    code="duplicate",
                    message=f"More than one file provides '{identifier}'. "
                    "The server may load the wrong one or fail to start.",
                    files=sorted(files),
                )
            )
    mismatched = [
        entry.file_name
        for entry in entries
        if entry.loaders and native and not (set(entry.loaders) & native)
    ]
    if mismatched:
        label = DISTRIBUTIONS.get(distribution, DISTRIBUTIONS["unknown"]).label
        warnings.append(
            ExtensionWarning(
                code="wrong-loader",
                message=f"These files declare support for a different loader and "
                f"will not work on a {label} server.",
                files=sorted(mismatched),
            )
        )
    client_only = [entry.file_name for entry in entries if entry.environment == "client"]
    if client_only:
        warnings.append(
            ExtensionWarning(
                code="client-only",
                message="These mods declare themselves client-only and do nothing on a server.",
                files=sorted(client_only),
            )
        )
    unreadable = [entry.file_name for entry in entries if not entry.readable]
    if unreadable:
        warnings.append(
            ExtensionWarning(
                code="unreadable",
                message="These files could not be read as jar archives.",
                files=sorted(unreadable),
            )
        )
    return warnings


def read_extensions(server_directory: Path, distribution: str) -> ExtensionsView:
    info = DISTRIBUTIONS.get(distribution, DISTRIBUTIONS["unknown"])
    if info.extension_directory is None:
        stray = [
            name
            for name in ("plugins", "mods")
            if (server_directory / name).is_dir() and any((server_directory / name).glob("*.jar"))
        ]
        warnings = (
            [
                ExtensionWarning(
                    code="unsupported",
                    message=f"This {info.label} server cannot load the jar files "
                    f"found in: {', '.join(stray)}.",
                    files=stray,
                )
            ]
            if stray
            else []
        )
        return ExtensionsView(
            directory=None, present=False, entries=[], warnings=warnings, truncated=False
        )
    folder = server_directory / info.extension_directory
    disabled = server_directory / f"{info.extension_directory}-disabled"
    disabled_entries = [_inspect_jar(jar) for jar in _list_jars(disabled)[:MAX_JARS]]
    if not folder.is_dir():
        return ExtensionsView(
            directory=info.extension_directory,
            present=False,
            entries=[],
            disabled_entries=disabled_entries,
            warnings=[],
            truncated=False,
        )
    jars = _list_jars(folder)
    entries = [_inspect_jar(jar) for jar in jars[:MAX_JARS]]
    return ExtensionsView(
        directory=info.extension_directory,
        present=True,
        entries=entries,
        disabled_entries=disabled_entries,
        warnings=_collect_warnings(distribution, entries),
        truncated=len(jars) > MAX_JARS,
    )


def _list_jars(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        (entry for entry in folder.iterdir() if entry.is_file() and entry.suffix == ".jar"),
        key=lambda entry: entry.name,
    )
