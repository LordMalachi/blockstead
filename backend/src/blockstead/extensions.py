"""Read-only inventory of plugin and mod jars.

Jars are opened as archives to read declared metadata only; nothing is
ever executed, moved, or rewritten. Warnings are advisory: metadata can
prove some incompatibilities, but it can never prove compatibility.
"""

import hashlib
import json
import re
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
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
MAX_INVENTORY_CACHE_ENTRIES = 128

_DirectorySignature = tuple[tuple[str, int, int, int, int], ...]
_InventoryKey = tuple[
    str, str, _DirectorySignature | None, _DirectorySignature | None, _DirectorySignature | None
]
_inventory_cache: OrderedDict[_InventoryKey, "ExtensionsView"] = OrderedDict()
_inventory_cache_lock = RLock()

#: The counterpart extension folder for each loader-defined one. A jar sitting
#: in the wrong one of these two (e.g. a Fabric mod dropped into ``plugins/``
#: on a Fabric server, or a Paper plugin dropped into ``mods/``) never loads,
#: so it is surfaced the same way stray jars on a vanilla profile are.
_STRAY_EXTENSION_DIRECTORY = {"plugins": "mods", "mods": "plugins"}

Kind = Literal["paper-plugin", "fabric-mod", "quilt-mod", "neoforge-mod", "forge-mod", "unknown"]

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
    sha512: str | None = None
    kind: Kind
    loaders: list[str]
    identifier: str | None
    display_name: str | None
    version: str | None
    minecraft_constraint: str | None
    environment: str | None
    dependencies: list[str]
    dependency_constraints: dict[str, str] = {}
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
    dependency_constraints: dict[str, str] = field(default_factory=dict)

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
        excluded = {"minecraft", "java", "fabricloader", "quilt_loader", "forge", "neoforge"}
        if not found.dependencies:
            found.dependencies = sorted(
                str(key)[:100] for key in depends if key not in excluded
            )
        if not found.dependency_constraints:
            found.dependency_constraints = {
                str(key)[:100]: cleaned
                for key, value in depends.items()
                if key not in excluded and (cleaned := _clean(value)) is not None
            }


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
    declared_constraints: dict[str, str] = {}
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
            cleaned = _clean(constraint)
            if cleaned is not None:
                declared_constraints[dep_id[:100]] = cleaned
    if declared and not found.dependencies:
        found.dependencies = sorted(declared)
    if declared_constraints and not found.dependency_constraints:
        found.dependency_constraints = declared_constraints


def _parse_mods_toml(raw: bytes, loader: str, found: _Metadata) -> None:
    try:
        data = tomllib.loads(raw.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, ValueError):
        return
    mods = data.get("mods")
    first = mods[0] if isinstance(mods, list) and mods and isinstance(mods[0], dict) else {}
    found.loaders.append(loader)
    if data.get("clientSideOnly") is True:
        found.fill("environment", "client")
    found.fill("identifier", _clean(first.get("modId")))
    found.fill("display_name", _clean(first.get("displayName")))
    found.fill("version", _clean(first.get("version")))
    mod_id = first.get("modId")
    dependencies = data.get("dependencies")
    declared: list[str] = []
    declared_constraints: dict[str, str] = {}
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
            cleaned = _clean(record.get("versionRange"))
            if cleaned is not None:
                declared_constraints[dep_id[:100]] = cleaned
    if declared and not found.dependencies:
        found.dependencies = sorted(declared)
    if declared_constraints and not found.dependency_constraints:
        found.dependency_constraints = declared_constraints


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
    # Bukkit's api-version is the oldest API a plugin targets, not an exact
    # Minecraft release. Paper continues loading that plugin on newer APIs.
    # Preserve that minimum-version meaning so command packs do not disappear
    # for long-lived plugins such as EssentialsX and LuckPerms.
    cleaned_api = _clean(str(api)) if api is not None else None
    found.fill(
        "minecraft_constraint",
        f">={cleaned_api}" if cleaned_api is not None else None,
    )
    depend = data.get("depend")
    if isinstance(depend, list) and not found.dependencies:
        found.dependencies = sorted(str(item)[:100] for item in depend if isinstance(item, str))
    # Paper's modern paper-plugin.yml puts dependencies in bootstrap and
    # server sections rather than Bukkit's legacy top-level `depend` list.
    nested = data.get("dependencies")
    required: list[str] = []
    if isinstance(nested, dict):
        for phase in ("bootstrap", "server"):
            records = nested.get(phase)
            if not isinstance(records, dict):
                continue
            required.extend(
                name[:100]
                for name, options in records.items()
                if isinstance(name, str)
                and (not isinstance(options, dict) or options.get("required", True) is not False)
            )
    if required and not found.dependencies:
        found.dependencies = sorted(set(required))


#: Simple Fabric/Quilt-style comparator prefixes, longest first so "==" is not
#: mis-split by the single-character "=" branch.
_SIMPLE_VERSION_OPERATORS = (">=", "<=", "==", "^", "~", ">", "<", "=")
_NUMERIC_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def _numeric_version_tuple(text: str) -> tuple[int, ...] | None:
    text = text.strip()
    if not _NUMERIC_VERSION_RE.match(text):
        return None
    return tuple(int(part) for part in text.split("."))


def _compare_numeric_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    length = max(len(left), len(right))
    left_padded = left + (0,) * (length - len(left))
    right_padded = right + (0,) * (length - len(right))
    if left_padded < right_padded:
        return -1
    if left_padded > right_padded:
        return 1
    return 0


def semver_constraint_satisfied(installed_version: str, constraint: str) -> bool | None:
    """Evaluate one simple Fabric/Quilt-style dependency version constraint.

    Supports a single ``>=``, ``<=``, ``>``, ``<``, ``=``/``==``, ``~``
    (tilde: same major.minor), ``^`` (caret: same major, or same
    major.minor when major is 0), a bare exact version, or ``*``.

    Returns ``True``/``False`` only when confidently determined. Returns
    ``None`` for syntax this cannot evaluate safely — comma/``||`` lists
    (Fabric and Quilt both allow multiple alternatives), wildcards, or a
    non-numeric version component — so a caller never turns a constraint it
    misread into a false "incompatible" verdict that blocks a legitimate
    install.
    """
    text = constraint.strip()
    if not text or text == "*":
        return True
    if "," in text or "||" in text or " - " in text or "x" in text.lower():
        return None
    operator = "="
    for candidate in _SIMPLE_VERSION_OPERATORS:
        if text.startswith(candidate):
            operator = "=" if candidate == "==" else candidate
            text = text[len(candidate) :].strip()
            break
    target = _numeric_version_tuple(text)
    current = _numeric_version_tuple(installed_version)
    if target is None or current is None:
        return None
    order = _compare_numeric_versions(current, target)
    if operator == "=":
        return order == 0
    if operator == ">=":
        return order >= 0
    if operator == "<=":
        return order <= 0
    if operator == ">":
        return order > 0
    if operator == "<":
        return order < 0
    if operator == "~":
        return _compare_numeric_versions(current[:2], target[:2]) == 0 and order >= 0
    if operator == "^":
        if target[:1] != (0,):
            return current[:1] == target[:1] and order >= 0
        return current[:2] == target[:2] and order >= 0
    return None  # pragma: no cover - every branch above is exhaustive


def maven_range_satisfied(installed_version: str, range_text: str) -> bool | None:
    """Evaluate a Forge/NeoForge Maven-style version range, e.g. ``[1.20,1.21)``.

    This syntax is an unambiguous, documented Maven format, so unlike
    :func:`semver_constraint_satisfied` this evaluates the full grammar:
    inclusive ``[``/``]`` and exclusive ``(``/``)`` bounds, an open bound on
    either side (``[1.20,)``), and a single bracketed version meaning an
    exact match (``[1.20.1]``). Returns ``None`` for a bare "recommended"
    version with no brackets — Maven treats that as a soft suggestion, not
    an enforced bound — or when a bound is not a plain numeric version.
    """
    text = range_text.strip()
    if len(text) < 2 or text[0] not in "[(" or text[-1] not in "])":
        return None
    body = text[1:-1]
    current = _numeric_version_tuple(installed_version)
    if current is None:
        return None
    if "," in body:
        low_text, _, high_text = body.partition(",")
    else:
        low_text = high_text = body
    low_text, high_text = low_text.strip(), high_text.strip()
    if low_text:
        low = _numeric_version_tuple(low_text)
        if low is None:
            return None
        comparison = _compare_numeric_versions(current, low)
        if text[0] == "[" and comparison < 0:
            return False
        if text[0] == "(" and comparison <= 0:
            return False
    if high_text:
        high = _numeric_version_tuple(high_text)
        if high is None:
            return None
        comparison = _compare_numeric_versions(current, high)
        if text[-1] == "]" and comparison > 0:
            return False
        if text[-1] == ")" and comparison >= 0:
            return False
    return True


def dependency_version_satisfied(kind: str, installed_version: str, constraint: str) -> bool | None:
    """Dispatch to the right evaluator for a dependency's declaring loader.

    Returns ``None`` (cannot verify) for any loader without a defined
    evaluator, or when the underlying evaluator itself cannot verify.
    """
    if kind in ("forge-mod", "neoforge-mod"):
        return maven_range_satisfied(installed_version, constraint)
    if kind in ("fabric-mod", "quilt-mod"):
        return semver_constraint_satisfied(installed_version, constraint)
    return None


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


def inspect_extension_jar(path: Path) -> ExtensionEntry:
    found = _Metadata()
    sha256: str | None = None
    sha512: str | None = None
    readable = False
    digest = hashlib.sha256()
    # Modrinth's update lookup identifies files by sha512, so record both.
    long_digest = hashlib.sha512()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                long_digest.update(chunk)
        sha256 = digest.hexdigest()
        sha512 = long_digest.hexdigest()
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
        sha512=sha512,
        kind=_kind_of(found.loaders) if readable else "unknown",
        loaders=found.loaders,
        identifier=found.identifier,
        display_name=found.display_name,
        version=found.version,
        minecraft_constraint=found.minecraft_constraint,
        environment=found.environment,
        dependencies=found.dependencies,
        dependency_constraints=found.dependency_constraints,
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


def _directory_signature(folder: Path) -> _DirectorySignature | None:
    """Return a cheap fingerprint for the jars relevant to an inventory."""
    try:
        if folder.is_symlink():
            return (("<symlink>", 0, 0, 0, 0),)
        if not folder.is_dir():
            return (("<missing>", 0, 0, 0, 0),)
        directory = folder.stat()
        records: list[tuple[str, int, int, int, int]] = [
            (
                "<directory>",
                directory.st_dev,
                directory.st_ino,
                directory.st_size,
                directory.st_mtime_ns,
            )
        ]
        for entry in folder.iterdir():
            if not entry.is_file() or entry.is_symlink() or entry.suffix.casefold() != ".jar":
                continue
            stat = entry.stat()
            records.append((entry.name, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        return tuple(sorted(records))
    except OSError:
        # An unreadable directory must be rescanned on the next request rather
        # than turning a transient filesystem error into cached evidence.
        return None


def _inventory_key(
    server_directory: Path, distribution: str, folder: Path, disabled: Path, stray: Path | None
) -> _InventoryKey:
    return (
        str(server_directory),
        distribution,
        _directory_signature(folder),
        _directory_signature(disabled),
        _directory_signature(stray) if stray is not None else (),
    )


def _cached_inventory(key: _InventoryKey) -> ExtensionsView | None:
    if any(component is None for component in key[2:]):
        return None
    with _inventory_cache_lock:
        cached = _inventory_cache.get(key)
        if cached is None:
            return None
        _inventory_cache.move_to_end(key)
        return cached.model_copy(deep=True)


def _store_inventory(key: _InventoryKey, view: ExtensionsView) -> None:
    if any(component is None for component in key[2:]):
        return
    with _inventory_cache_lock:
        _inventory_cache[key] = view.model_copy(deep=True)
        _inventory_cache.move_to_end(key)
        while len(_inventory_cache) > MAX_INVENTORY_CACHE_ENTRIES:
            _inventory_cache.popitem(last=False)


def read_extensions(server_directory: Path, distribution: str) -> ExtensionsView:
    # Active readable entries are the only inventory evidence that may unlock
    # extension command packs; disabled entries are installer state only.
    info = DISTRIBUTIONS.get(distribution, DISTRIBUTIONS["unknown"])
    if info.extension_directory is None:
        stray = [
            name
            for name in ("plugins", "mods")
            if (server_directory / name).is_dir() and _list_jars(server_directory / name)
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
    stray_name = _STRAY_EXTENSION_DIRECTORY[info.extension_directory]
    stray_dir = server_directory / stray_name
    key = _inventory_key(server_directory, distribution, folder, disabled, stray_dir)
    cached = _cached_inventory(key)
    if cached is not None:
        return cached
    disabled_entries = [inspect_extension_jar(jar) for jar in _list_jars(disabled)[:MAX_JARS]]
    stray_jars = [jar.name for jar in _list_jars(stray_dir)]
    stray_warnings = (
        [
            ExtensionWarning(
                code="wrong-directory",
                message=f"These files are in {stray_name}/, which this {info.label} server "
                f"does not load. Move them into {info.extension_directory}/ if they belong "
                f"here, or remove them.",
                files=sorted(stray_jars),
            )
        ]
        if stray_jars
        else []
    )
    if not folder.is_dir():
        view = ExtensionsView(
            directory=info.extension_directory,
            present=False,
            entries=[],
            disabled_entries=disabled_entries,
            warnings=stray_warnings,
            truncated=False,
        )
        # A directory that changed mid-scan just produces a signature the next
        # independent read won't match, so it self-heals without a re-verify
        # scan here; store under the key already fingerprinted above.
        _store_inventory(key, view)
        return view
    jars = _list_jars(folder)
    entries = [inspect_extension_jar(jar) for jar in jars[:MAX_JARS]]
    view = ExtensionsView(
        directory=info.extension_directory,
        present=True,
        entries=entries,
        disabled_entries=disabled_entries,
        warnings=[*_collect_warnings(distribution, entries), *stray_warnings],
        truncated=len(jars) > MAX_JARS,
    )
    _store_inventory(key, view)
    return view


def _list_jars(folder: Path) -> list[Path]:
    if folder.is_symlink() or not folder.is_dir():
        return []
    return sorted(
        (
            entry
            for entry in folder.iterdir()
            if entry.is_file() and not entry.is_symlink() and entry.suffix.casefold() == ".jar"
        ),
        key=lambda entry: entry.name,
    )
