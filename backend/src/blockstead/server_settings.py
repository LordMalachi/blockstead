"""Typed, revision-aware editing for Minecraft ``server.properties`` files."""

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel

MAX_FILE_BYTES = 1_000_000

SettingType = Literal["string", "integer", "boolean"]
SettingCategory = Literal["Gameplay", "Players", "World", "Network", "Performance"]
SettingValue = str | int | bool


class SettingsConflictError(RuntimeError):
    """The source file changed or disappeared before a safe write."""


class SettingsValidationError(ValueError):
    """A requested value is not safe or valid for its Minecraft setting."""


@dataclass(frozen=True)
class SettingDefinition:
    type: SettingType
    label: str
    category: SettingCategory
    description: str
    minimum: int | None = None
    maximum: int | None = None
    options: tuple[str, ...] = ()
    max_length: int | None = None
    pattern: str | None = None
    restart_required: bool = True


KNOWN_SETTINGS: dict[str, SettingDefinition] = {
    "gamemode": SettingDefinition(
        "string",
        "Default game mode",
        "Gameplay",
        "Mode used when a player first joins.",
        options=("survival", "creative", "adventure", "spectator"),
    ),
    "difficulty": SettingDefinition(
        "string",
        "Difficulty",
        "Gameplay",
        "Controls hostile mobs and survival difficulty.",
        options=("peaceful", "easy", "normal", "hard"),
    ),
    "hardcore": SettingDefinition(
        "boolean",
        "Hardcore mode",
        "Gameplay",
        "Locks the world to hard difficulty and one life.",
    ),
    "pvp": SettingDefinition(
        "boolean",
        "Player-versus-player combat",
        "Gameplay",
        "Allows players to damage each other.",
    ),
    "allow-flight": SettingDefinition(
        "boolean",
        "Allow flight",
        "Gameplay",
        "Avoids kicking players when legitimate flight is detected.",
    ),
    "enable-command-block": SettingDefinition(
        "boolean",
        "Command blocks",
        "Gameplay",
        "Allows command blocks to execute commands.",
    ),
    "motd": SettingDefinition(
        "string",
        "Server list message",
        "Players",
        "Message shown beside the server in Minecraft.",
        max_length=200,
    ),
    "max-players": SettingDefinition(
        "integer",
        "Player limit",
        "Players",
        "Maximum number of simultaneous players.",
        minimum=1,
        maximum=1000,
    ),
    "online-mode": SettingDefinition(
        "boolean",
        "Verify Minecraft accounts",
        "Players",
        "Checks player identities with Minecraft services.",
    ),
    "white-list": SettingDefinition(
        "boolean",
        "Require allowlist",
        "Players",
        "Only permits players on the allowlist.",
    ),
    "enforce-whitelist": SettingDefinition(
        "boolean",
        "Enforce allowlist immediately",
        "Players",
        "Removes connected players who are not allowed.",
    ),
    "level-name": SettingDefinition(
        "string",
        "World folder",
        "World",
        "Folder name containing the primary world.",
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$",
    ),
    "allow-nether": SettingDefinition(
        "boolean",
        "Allow the Nether",
        "World",
        "Enables travel to the Nether dimension.",
    ),
    "spawn-protection": SettingDefinition(
        "integer",
        "Spawn protection radius",
        "World",
        "Protected block radius around world spawn.",
        minimum=0,
        maximum=1000,
    ),
    "server-port": SettingDefinition(
        "integer",
        "Server port",
        "Network",
        "TCP port players use to join this server.",
        minimum=1,
        maximum=65535,
    ),
    "view-distance": SettingDefinition(
        "integer",
        "View distance",
        "Performance",
        "Maximum chunk radius sent to each player.",
        minimum=2,
        maximum=32,
    ),
    "simulation-distance": SettingDefinition(
        "integer",
        "Simulation distance",
        "Performance",
        "Chunk radius where entities and redstone keep ticking.",
        minimum=2,
        maximum=32,
    ),
}

SECRET_MARKERS = ("password", "secret", "token")


class SettingEntry(BaseModel):
    key: str
    label: str
    category: SettingCategory
    description: str
    type: SettingType
    value: SettingValue | None
    minimum: int | None
    maximum: int | None
    options: list[str]
    restart_required: bool


class SettingsView(BaseModel):
    present: bool
    revision: str | None
    settings: list[SettingEntry]
    other_keys: list[str]


class SettingDiff(BaseModel):
    key: str
    label: str
    category: SettingCategory
    before: SettingValue | None
    after: SettingValue
    restart_required: bool


class SettingsPreview(BaseModel):
    revision: str
    changes: list[SettingDiff]
    restart_required: bool


class SettingsApplyResult(BaseModel):
    snapshot_name: str
    previous_revision: str
    revision: str
    changes: list[SettingDiff]
    restart_required: bool
    view: SettingsView


class RawSettingsView(BaseModel):
    present: bool
    editable: bool
    problem: str | None
    revision: str | None
    content: str | None
    secret_keys: list[str]


class RawSettingsPreview(BaseModel):
    revision: str
    valid: bool
    problems: list[str]
    no_changes: bool
    changed_known: list[SettingDiff]
    removed_known: list[str]
    other_lines_changed: bool
    restart_required: bool


class RawSettingsApplyResult(BaseModel):
    snapshot_name: str
    previous_revision: str
    revision: str
    changed_known: list[SettingDiff]
    removed_known: list[str]
    other_lines_changed: bool
    restart_required: bool
    view: SettingsView


def _read_limited(path: Path) -> bytes | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _revision(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        values[key.strip()] = raw.strip()
    return values


def _typed_value(kind: SettingType, raw: str) -> SettingValue | None:
    if kind == "boolean":
        return raw.lower() == "true" if raw.lower() in {"true", "false"} else None
    if kind == "integer":
        try:
            return int(raw)
        except ValueError:
            return None
    return raw


def read_settings(server_directory: Path) -> SettingsView:
    raw = _read_limited(server_directory / "server.properties")
    if raw is None:
        return SettingsView(present=False, revision=None, settings=[], other_keys=[])
    text = raw.decode("utf-8", errors="replace")
    values = _values(text)
    settings = [
        SettingEntry(
            key=key,
            label=definition.label,
            category=definition.category,
            description=definition.description,
            type=definition.type,
            value=_typed_value(definition.type, values[key]),
            minimum=definition.minimum,
            maximum=definition.maximum,
            options=list(definition.options),
            restart_required=definition.restart_required,
        )
        for key, definition in KNOWN_SETTINGS.items()
        if key in values
    ]
    other = sorted(
        key
        for key in values
        if key not in KNOWN_SETTINGS and not any(marker in key.lower() for marker in SECRET_MARKERS)
    )
    return SettingsView(
        present=True,
        revision=_revision(raw),
        settings=settings,
        other_keys=other,
    )


SECRET_PLACEHOLDER = "••••••••"  # noqa: S105  # display mask, not a credential
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _is_secret(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _split_line(content: str) -> tuple[str, str] | None:
    stripped = content.strip()
    if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    return key.strip(), value.strip()


def _lines_with_endings(text: str) -> list[tuple[str, str]]:
    lines = []
    for line in text.splitlines(keepends=True):
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        lines.append((line[: -len(ending)] if ending else line, ending))
    return lines


def read_raw_settings(server_directory: Path) -> RawSettingsView:
    """The complete file for advanced editing, with secret values hidden."""

    raw = _read_limited(server_directory / "server.properties")
    if raw is None:
        return RawSettingsView(
            present=False,
            editable=False,
            problem="No readable server.properties file was found in this profile folder.",
            revision=None,
            content=None,
            secret_keys=[],
        )
    revision = _revision(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return RawSettingsView(
            present=True,
            editable=False,
            problem="server.properties is not valid UTF-8, so raw editing was refused.",
            revision=revision,
            content=None,
            secret_keys=[],
        )
    secret_keys: list[str] = []
    output: list[str] = []
    for content, ending in _lines_with_endings(text):
        parsed = _split_line(content)
        if parsed and _is_secret(parsed[0]) and parsed[1]:
            equals = content.index("=")
            content = f"{content[: equals + 1]}{SECRET_PLACEHOLDER}"
            if parsed[0] not in secret_keys:
                secret_keys.append(parsed[0])
        output.append(content + ending)
    return RawSettingsView(
        present=True,
        editable=True,
        problem=None,
        revision=revision,
        content="".join(output),
        secret_keys=sorted(secret_keys),
    )


def _restore_secrets(original_text: str, submitted: str, problems: list[str]) -> str:
    """Swap hidden placeholders back to the real values from the current file."""

    originals: dict[str, list[str]] = {}
    for line in original_text.splitlines():
        parsed = _split_line(line)
        if parsed and _is_secret(parsed[0]) and parsed[1]:
            originals.setdefault(parsed[0], []).append(parsed[1])
    output: list[str] = []
    for number, (content, ending) in enumerate(_lines_with_endings(submitted), start=1):
        parsed = _split_line(content)
        if parsed and _is_secret(parsed[0]) and parsed[1] == SECRET_PLACEHOLDER:
            remaining = originals.get(parsed[0])
            if remaining:
                equals = content.index("=")
                content = f"{content[: equals + 1]}{remaining.pop(0)}"
            else:
                problems.append(
                    f"Line {number}: the hidden value for {parsed[0]} is not available. "
                    "Enter a real value or remove the line."
                )
        output.append(content + ending)
    return "".join(output)


def _validate_raw_text(text: str) -> tuple[dict[str, str], list[str]]:
    problems: list[str] = []
    if _CONTROL_CHARACTERS.search(text):
        problems.append("The file contains control characters that are not allowed.")
    values: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")):
            continue
        if "=" not in stripped:
            problems.append(f"Line {number} is not a key=value setting or a # comment.")
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            problems.append(f"Line {number} is missing a setting name before '='.")
            continue
        if key in values:
            problems.append(f"Line {number} repeats the setting {key}.")
            continue
        values[key] = value.strip()
        definition = KNOWN_SETTINGS.get(key)
        if definition is None:
            continue
        typed = _typed_value(definition.type, value.strip())
        if typed is None:
            expectation = (
                "true or false" if definition.type == "boolean" else "a whole number"
            )
            problems.append(f"Line {number}: {definition.label} must be {expectation}.")
            continue
        try:
            _validate_value(key, typed)
        except SettingsValidationError as exc:
            problems.append(f"Line {number}: {exc}")
    if (
        _typed_value("boolean", values.get("enforce-whitelist", "")) is True
        and _typed_value("boolean", values.get("white-list", "")) is False
    ):
        problems.append(
            "Immediate allowlist enforcement requires the allowlist to be enabled."
        )
    return values, problems


def _raw_summary(
    original_text: str, original_values: dict[str, str], restored: str
) -> tuple[list[SettingDiff], list[str], bool]:
    new_values = _values(restored)
    changed = [
        SettingDiff(
            key=key,
            label=definition.label,
            category=definition.category,
            before=_typed_value(definition.type, original_values[key])
            if key in original_values
            else None,
            after=after,
            restart_required=definition.restart_required,
        )
        for key, definition in KNOWN_SETTINGS.items()
        if key in new_values
        and (after := _typed_value(definition.type, new_values[key])) is not None
        and after
        != (
            _typed_value(definition.type, original_values[key])
            if key in original_values
            else None
        )
    ]
    removed = [
        key
        for key in KNOWN_SETTINGS
        if key in original_values and key not in new_values
    ]

    def other_lines(text: str) -> list[str]:
        kept = []
        for line in text.splitlines():
            parsed = _split_line(line)
            if parsed and parsed[0] in KNOWN_SETTINGS:
                continue
            kept.append(line.rstrip("\r"))
        return kept

    other_changed = other_lines(original_text) != other_lines(restored)
    return changed, removed, other_changed


def _plan_raw_update(
    server_directory: Path, expected_revision: str, content: str
) -> tuple[Path, bytes, str, RawSettingsPreview]:
    path, raw, text, values = _source(server_directory)
    current_revision = _revision(raw)
    if current_revision != expected_revision:
        raise SettingsConflictError(
            "server.properties changed after it was opened. Reload settings and review again."
        )
    problems: list[str] = []
    restored = _restore_secrets(text, content, problems)
    if restored and not restored.endswith(("\n", "\r")):
        restored += "\r\n" if "\r\n" in text else "\n"
    _, more_problems = _validate_raw_text(restored)
    problems.extend(more_problems)
    changed, removed, other_changed = _raw_summary(text, values, restored)
    preview = RawSettingsPreview(
        revision=current_revision,
        valid=not problems,
        problems=problems,
        no_changes=restored.rstrip("\r\n") == text.rstrip("\r\n"),
        changed_known=changed,
        removed_known=removed,
        other_lines_changed=other_changed,
        restart_required=bool(
            any(change.restart_required for change in changed) or removed or other_changed
        ),
    )
    return path, raw, restored, preview


def preview_raw_settings(
    server_directory: Path, expected_revision: str, content: str
) -> RawSettingsPreview:
    return _plan_raw_update(server_directory, expected_revision, content)[3]


def apply_raw_settings(
    server_directory: Path,
    snapshot_root: Path,
    profile_id: str,
    expected_revision: str,
    content: str,
) -> RawSettingsApplyResult:
    path, raw, restored, preview = _plan_raw_update(
        server_directory, expected_revision, content
    )
    if preview.problems:
        raise SettingsValidationError(" ".join(preview.problems))
    if preview.no_changes:
        raise SettingsValidationError("Nothing changed in server.properties.")

    snapshot_name = _write_snapshot(snapshot_root, profile_id, raw)
    _replace_atomically(server_directory, path, raw, restored.encode("utf-8"))

    view = read_settings(server_directory)
    assert view.revision is not None
    return RawSettingsApplyResult(
        snapshot_name=snapshot_name,
        previous_revision=preview.revision,
        revision=view.revision,
        changed_known=preview.changed_known,
        removed_known=preview.removed_known,
        other_lines_changed=preview.other_lines_changed,
        restart_required=preview.restart_required,
        view=view,
    )


def _source(server_directory: Path) -> tuple[Path, bytes, str, dict[str, str]]:
    path = server_directory / "server.properties"
    raw = _read_limited(path)
    if raw is None:
        raise SettingsConflictError("No editable server.properties file was found.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SettingsValidationError(
            "server.properties is not valid UTF-8, so guided editing was refused."
        ) from exc
    return path, raw, text, _values(text)


def _validate_value(key: str, value: SettingValue) -> SettingValue:
    definition = KNOWN_SETTINGS.get(key)
    if definition is None:
        raise SettingsValidationError(f"{key} is not available in the guided editor.")
    if definition.type == "boolean":
        if type(value) is not bool:
            raise SettingsValidationError(f"{definition.label} must be on or off.")
    elif definition.type == "integer":
        if type(value) is not int:
            raise SettingsValidationError(f"{definition.label} must be a whole number.")
        if definition.minimum is not None and value < definition.minimum:
            raise SettingsValidationError(
                f"{definition.label} must be at least {definition.minimum}."
            )
        if definition.maximum is not None and value > definition.maximum:
            raise SettingsValidationError(
                f"{definition.label} must be no more than {definition.maximum}."
            )
    else:
        if type(value) is not str:
            raise SettingsValidationError(f"{definition.label} must be text.")
        if any(character in value for character in "\r\n\x00"):
            raise SettingsValidationError(f"{definition.label} must fit on one line.")
        if definition.max_length is not None and len(value) > definition.max_length:
            raise SettingsValidationError(
                f"{definition.label} must be at most {definition.max_length} characters."
            )
        if definition.options and value not in definition.options:
            choices = ", ".join(definition.options)
            raise SettingsValidationError(f"{definition.label} must be one of: {choices}.")
        if definition.pattern and re.fullmatch(definition.pattern, value) is None:
            raise SettingsValidationError(
                f"{definition.label} may use letters, numbers, dots, underscores, and dashes."
            )
    return value


def _plan_update(
    server_directory: Path,
    expected_revision: str,
    requested: dict[str, SettingValue],
) -> tuple[Path, bytes, str, SettingsPreview, dict[str, SettingValue]]:
    path, raw, text, values = _source(server_directory)
    current_revision = _revision(raw)
    if current_revision != expected_revision:
        raise SettingsConflictError(
            "server.properties changed after it was opened. Reload settings and review again."
        )
    validated = {key: _validate_value(key, value) for key, value in requested.items()}
    merged: dict[str, SettingValue | None] = {
        key: _typed_value(definition.type, raw_value)
        for key, definition in KNOWN_SETTINGS.items()
        if (raw_value := values.get(key)) is not None
    }
    merged.update(validated)
    if (
        {"white-list", "enforce-whitelist"} & validated.keys()
        and merged.get("enforce-whitelist") is True
        and merged.get("white-list") is False
    ):
        raise SettingsValidationError(
            "Immediate allowlist enforcement requires the allowlist to be enabled."
        )
    changes = [
        SettingDiff(
            key=key,
            label=definition.label,
            category=definition.category,
            before=_typed_value(definition.type, values[key]) if key in values else None,
            after=validated[key],
            restart_required=definition.restart_required,
        )
        for key, definition in KNOWN_SETTINGS.items()
        if key in validated
        and (_typed_value(definition.type, values[key]) if key in values else None)
        != validated[key]
    ]
    return (
        path,
        raw,
        text,
        SettingsPreview(
            revision=current_revision,
            changes=changes,
            restart_required=any(change.restart_required for change in changes),
        ),
        validated,
    )


def preview_settings_update(
    server_directory: Path,
    expected_revision: str,
    requested: dict[str, SettingValue],
) -> SettingsPreview:
    return _plan_update(server_directory, expected_revision, requested)[3]


def _updated_text(text: str, changes: dict[str, SettingValue]) -> str:
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    found: set[str] = set()
    output: list[str] = []
    for line in lines:
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        content = line[: -len(ending)] if ending else line
        stripped = content.strip()
        if stripped and not stripped.startswith(("#", "!")) and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in changes:
                equals = content.index("=")
                value = changes[key]
                serialized = str(value).lower() if type(value) is bool else str(value)
                content = f"{content[: equals + 1]}{serialized}"
                found.add(key)
        output.append(content + ending)
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += newline
    for key, value in changes.items():
        if key not in found:
            serialized = str(value).lower() if type(value) is bool else str(value)
            output.append(f"{key}={serialized}{newline}")
    return "".join(output)


def _write_snapshot(snapshot_root: Path, profile_id: str, raw: bytes) -> str:
    snapshot_directory = snapshot_root / "settings-snapshots" / profile_id
    snapshot_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_directory.chmod(0o700)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    snapshot_name = f"{stamp}-{uuid4().hex[:8]}.properties"
    snapshot = snapshot_directory / snapshot_name
    with snapshot.open("xb") as handle:
        os.chmod(handle.fileno(), 0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return snapshot_name


def _replace_atomically(
    server_directory: Path, path: Path, raw: bytes, updated: bytes
) -> None:
    staging = server_directory / f".server.properties.{uuid4().hex}.tmp"
    try:
        with staging.open("xb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        staging.chmod(path.stat().st_mode & 0o777)
        if path.read_bytes() != raw:
            raise SettingsConflictError(
                "server.properties changed while the update was being prepared. Reload and retry."
            )
        os.replace(staging, path)
    except (OSError, SettingsConflictError):
        staging.unlink(missing_ok=True)
        raise


def apply_settings_update(
    server_directory: Path,
    snapshot_root: Path,
    profile_id: str,
    expected_revision: str,
    requested: dict[str, SettingValue],
) -> SettingsApplyResult:
    path, raw, text, preview, validated = _plan_update(
        server_directory, expected_revision, requested
    )
    if not preview.changes:
        raise SettingsValidationError("No setting values changed.")

    snapshot_name = _write_snapshot(snapshot_root, profile_id, raw)
    updated = _updated_text(text, validated).encode("utf-8")
    _replace_atomically(server_directory, path, raw, updated)

    view = read_settings(server_directory)
    assert view.revision is not None
    return SettingsApplyResult(
        snapshot_name=snapshot_name,
        previous_revision=preview.revision,
        revision=view.revision,
        changes=preview.changes,
        restart_required=preview.restart_required,
        view=view,
    )
