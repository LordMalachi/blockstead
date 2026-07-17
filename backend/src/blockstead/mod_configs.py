"""Bounded, revision-safe editing for loader configuration files."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

MAX_CONFIG_FILES = 250
MAX_CONFIG_BYTES = 1_000_000
EDITABLE_SUFFIXES = frozenset(
    {".cfg", ".conf", ".json", ".json5", ".properties", ".toml", ".txt", ".yaml", ".yml"}
)


class ModConfigError(ValueError):
    """A configuration path or edit was unsafe or stale; message is user-safe."""


class ModConfigEntry(BaseModel):
    path: str
    size_bytes: int


class ModConfigDocument(BaseModel):
    path: str
    content: str
    revision: str
    size_bytes: int


def _config_root(server_directory: Path) -> Path:
    return server_directory / "config"


def _target(server_directory: Path, raw_path: str) -> Path:
    relative = PurePosixPath(raw_path.replace("\\", "/"))
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} or part.startswith(".") for part in relative.parts)
        or relative.suffix.lower() not in EDITABLE_SUFFIXES
    ):
        raise ModConfigError("That is not an editable loader configuration path.")
    root = _config_root(server_directory).resolve()
    requested = root / relative
    try:
        target = requested.resolve(strict=True)
    except OSError as exc:
        raise ModConfigError("That configuration file was not found in this profile.") from exc
    if root not in target.parents or not target.is_file() or requested.is_symlink():
        raise ModConfigError("That configuration file was not found in this profile.")
    return target


def list_mod_configs(server_directory: Path) -> list[ModConfigEntry]:
    root = _config_root(server_directory)
    if not root.is_dir() or root.is_symlink():
        return []
    entries: list[ModConfigEntry] = []
    for candidate in sorted(root.rglob("*")):
        if len(entries) >= MAX_CONFIG_FILES:
            break
        try:
            if (
                not candidate.is_file()
                or candidate.is_symlink()
                or candidate.suffix.lower() not in EDITABLE_SUFFIXES
                or any(part.startswith(".") for part in candidate.relative_to(root).parts)
            ):
                continue
            resolved = candidate.resolve(strict=True)
            if root.resolve() not in resolved.parents:
                continue
            size = candidate.stat().st_size
        except (OSError, ValueError):
            continue
        if size <= MAX_CONFIG_BYTES:
            entries.append(
                ModConfigEntry(path=candidate.relative_to(root).as_posix(), size_bytes=size)
            )
    return entries


def read_mod_config(server_directory: Path, path: str) -> ModConfigDocument:
    target = _target(server_directory, path)
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ModConfigError("That configuration file could not be read.") from exc
    if len(data) > MAX_CONFIG_BYTES:
        raise ModConfigError("That configuration file is larger than Blockstead can edit.")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ModConfigError("That configuration file is not UTF-8 text.") from exc
    return ModConfigDocument(
        path=path,
        content=content,
        revision=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _validate_content(suffix: str, content: str) -> None:
    try:
        if suffix == ".json":
            json.loads(content)
        elif suffix == ".toml":
            tomllib.loads(content)
        elif suffix in {".yaml", ".yml"}:
            yaml.safe_load(content)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, yaml.YAMLError, ValueError) as exc:
        raise ModConfigError(f"The edited {suffix[1:].upper()} is not valid: {exc}") from exc


def write_mod_config(
    server_directory: Path, path: str, revision: str, content: str
) -> ModConfigDocument:
    current = read_mod_config(server_directory, path)
    if current.revision != revision:
        raise ModConfigError("That file changed after you opened it. Reload it before saving.")
    if "\x00" in content:
        raise ModConfigError("Configuration text cannot contain null bytes.")
    data = content.encode("utf-8")
    if len(data) > MAX_CONFIG_BYTES:
        raise ModConfigError("The edited configuration is larger than Blockstead can save.")
    target = _target(server_directory, path)
    _validate_content(target.suffix.lower(), content)
    backup_root = server_directory / ".blockstead-config-backups"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_root / f"{PurePosixPath(path).as_posix()}.{stamp}.{revision[:12]}.bak"
    staging = target.with_name(f".{target.name}.blockstead.tmp")
    try:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
        staging.write_bytes(data)
        staging.chmod(target.stat().st_mode)
        staging.replace(target)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise ModConfigError("Blockstead could not safely save that configuration file.") from exc
    return read_mod_config(server_directory, path)
