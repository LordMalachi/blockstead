"""Private startup validation and reviewed-batch quarantine.

The service in this module is deliberately independent of FastAPI and the
database. API handlers provide an already-authorized profile, the shared
``ProcessManager``, and (when applicable) the files returned by a reviewed
manual import. The service then:

* binds the validation server to loopback on an ephemeral port;
* starts a disposable validation world instead of the owner's world;
* restores ``server.properties`` byte-for-byte after the process stops;
* returns bounded startup evidence; and
* atomically moves only the reviewed batch to the existing disabled directory
  when startup fails.

Nothing in this module executes extension jars directly or removes a world.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import stat
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .distributions import DISTRIBUTIONS, LaunchPlanError, launch_arguments
from .extension_ops import (
    ExtensionOpsError,
    disabled_directory,
    ensure_managed_directory,
)
from .extensions import ExtensionEntry
from .modrinth import JAR_NAME_PATTERN
from .process import InvalidTransition, LogEvent, ProcessManager, ProcessState

MAX_PROPERTIES_BYTES = 1_000_000
DEFAULT_READY_TIMEOUT_SECONDS = 120.0
DEFAULT_STOP_TIMEOUT_SECONDS = 15.0
DEFAULT_EVIDENCE_LINES = 120
DEFAULT_EVIDENCE_CHARACTERS = 24_000
VALIDATION_WORLD_PREFIX = "blockstead-validation-"
REVIEWED_BATCH_DIRECTORY = ".blockstead-reviewed-batches"
REVIEWED_BATCH_RETENTION_SECONDS = 7 * 24 * 60 * 60
REVIEWED_BATCH_MAX_RECORDS = 25
VALIDATION_WORKSPACE_RETENTION_SECONDS = 24 * 60 * 60

FailureKind = Literal[
    "extension_error",
    "java_error",
    "startup_crash",
    "startup_timeout",
    "launch_error",
    "cleanup_error",
]
ValidationStatus = Literal["passed", "failed"]

_EXTENSION_FAILURE_MARKERS = (
    re.compile(r"\bmissing (?:required )?dependenc", re.IGNORECASE),
    re.compile(r"\brequires .+ (?:mod|plugin|version)", re.IGNORECASE),
    re.compile(r"\bincompatible (?:mod|plugin)", re.IGNORECASE),
    re.compile(r"\bmod resolution encountered", re.IGNORECASE),
    re.compile(r"\bfailed to load (?:mod|plugin)", re.IGNORECASE),
    re.compile(r"\bcould not load .+\.(?:jar|mod|plugin)", re.IGNORECASE),
    re.compile(r"\bduplicate (?:mod|plugin)", re.IGNORECASE),
)
_JAVA_FAILURE_MARKERS = (
    re.compile(r"UnsupportedClassVersionError"),
    re.compile(r"NoClassDefFoundError"),
    re.compile(r"Could not find or load main class", re.IGNORECASE),
    re.compile(r"Unable to access jarfile", re.IGNORECASE),
)


class SafeStartError(ValueError):
    """A safe-start request was refused; its message is suitable for an owner."""


class ReviewedBatchFile(BaseModel):
    file_name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    identifier: str | None = None
    display_name: str | None = None
    version: str | None = None


class ReviewedExtensionBatch(BaseModel):
    """The exact live files promoted by one reviewed install transaction."""

    review_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    destination: str = Field(pattern=r"^(mods|plugins)$")
    files: list[ReviewedBatchFile] = Field(min_length=1, max_length=20)
    created_at: int


class SafeStartPlan(BaseModel):
    profile_id: str = Field(min_length=1, max_length=36)
    distribution: str = Field(pattern=r"^(paper|fabric|forge|quilt|neoforge)$")
    server_directory: str
    validation_directory: str
    java_executable: str
    arguments: list[str] | None = None
    validation_owner: str
    validation_world: str
    private_overrides: dict[str, str]
    reviewed_batch: ReviewedExtensionBatch | None = None


class StartupEvidence(BaseModel):
    sequence: int
    timestamp: str
    line: str


class QuarantineResult(BaseModel):
    attempted: bool
    succeeded: bool
    destination: str | None = None
    files: list[str] = []
    detail: str | None = None


class SafeStartResult(BaseModel):
    profile_id: str
    status: ValidationStatus
    failure_kind: FailureKind | None = None
    detail: str
    ready: bool
    exit_code: int | None
    duration_ms: int
    evidence: list[StartupEvidence]
    evidence_truncated: bool
    properties_restored: bool
    validation_world_removed: bool
    validation_workspace_removed: bool
    quarantine: QuarantineResult
    warnings: list[str] = []


def _eula_accepted(directory: Path) -> bool:
    path = directory / "eula.txt"
    try:
        return path.is_file() and "eula=true" in path.read_text(
            encoding="utf-8", errors="replace"
        )[:4096].lower()
    except OSError:
        return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise SafeStartError(f"Blockstead could not verify {path.name}.") from exc
    return digest.hexdigest()


def identify_reviewed_batch(
    extension_directory: Path,
    review_id: str,
    reviewed_entries: Iterable[ExtensionEntry | dict[str, object]],
) -> ReviewedExtensionBatch:
    """Identify and re-verify jars installed by one completed review.

    Call this immediately after ``promote_staged_files`` using the entries that
    were re-inspected during apply. It refuses missing, changed, duplicated, or
    disabled files, so a later failed validation can quarantine exactly this
    transaction and nothing else.
    """

    if not re.fullmatch(r"[0-9a-f]{16}", review_id):
        raise SafeStartError("The reviewed extension batch has an invalid identity.")
    directory = ensure_managed_directory(extension_directory)
    if directory.name not in {"mods", "plugins"}:
        raise SafeStartError("The reviewed batch does not belong to a managed loadout.")

    files: list[ReviewedBatchFile] = []
    seen: set[str] = set()
    for raw in reviewed_entries:
        entry = raw if isinstance(raw, ExtensionEntry) else ExtensionEntry.model_validate(raw)
        if entry.file_name in seen or not JAR_NAME_PATTERN.fullmatch(entry.file_name):
            raise SafeStartError("The reviewed extension batch contains an unsafe duplicate.")
        seen.add(entry.file_name)
        path = directory / entry.file_name
        if path.is_symlink() or not path.is_file():
            raise SafeStartError(
                f"{entry.file_name} is no longer installed in the reviewed loadout."
            )
        digest = _sha256(path)
        if entry.sha256 is None or digest != entry.sha256.casefold():
            raise SafeStartError(
                f"{entry.file_name} changed after its installation review."
            )
        files.append(
            ReviewedBatchFile(
                file_name=entry.file_name,
                sha256=digest,
                identifier=entry.identifier,
                display_name=entry.display_name,
                version=entry.version,
            )
        )
    if not files:
        raise SafeStartError("The reviewed extension batch contains no installed jars.")
    return ReviewedExtensionBatch(
        review_id=review_id,
        destination=directory.name,
        files=files,
        created_at=int(time.time()),
    )


def _reviewed_batch_store(extension_directory: Path, *, create: bool = False) -> Path:
    directory = ensure_managed_directory(extension_directory)
    store = directory / REVIEWED_BATCH_DIRECTORY
    if store.is_symlink():
        raise SafeStartError("The reviewed-batch record folder cannot be a symbolic link.")
    if store.exists() and not store.is_dir():
        raise SafeStartError("The reviewed-batch record path is not a folder.")
    if create:
        try:
            store.mkdir(mode=0o700, exist_ok=True)
        except OSError as exc:
            raise SafeStartError("Blockstead could not save the reviewed batch.") from exc
    return store


def save_reviewed_batch(
    extension_directory: Path, batch: ReviewedExtensionBatch
) -> Path:
    """Durably retain a promoted review after its upload staging is deleted."""

    _verify_batch(extension_directory, batch)
    store = _reviewed_batch_store(extension_directory, create=True)
    target = store / f"{batch.review_id}.json"
    staging = store / f".{batch.review_id}-{secrets.token_hex(8)}.part"
    try:
        with staging.open("x", encoding="utf-8") as handle:
            handle.write(batch.model_dump_json())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staging, target)
        _fsync_directory(store)
    except OSError as exc:
        raise SafeStartError("Blockstead could not save the reviewed batch.") from exc
    finally:
        staging.unlink(missing_ok=True)
    return target


def load_reviewed_batch(
    extension_directory: Path, review_id: str
) -> ReviewedExtensionBatch:
    """Load and re-verify a durable reviewed batch for validation."""

    if not re.fullmatch(r"[0-9a-f]{16}", review_id):
        raise SafeStartError("The reviewed extension batch has an invalid identity.")
    path = _reviewed_batch_store(extension_directory) / f"{review_id}.json"
    try:
        batch = ReviewedExtensionBatch.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SafeStartError("That reviewed extension batch is no longer available.") from exc
    if batch.review_id != review_id:
        raise SafeStartError("That reviewed extension batch has an invalid record.")
    if time.time() - batch.created_at > REVIEWED_BATCH_RETENTION_SECONDS:
        path.unlink(missing_ok=True)
        raise SafeStartError("That reviewed extension batch expired.")
    _verify_batch(extension_directory, batch)
    return batch


def delete_reviewed_batch(
    extension_directory: Path, review_id: str
) -> None:
    """Delete one validated record, never an installed extension."""

    if not re.fullmatch(r"[0-9a-f]{16}", review_id):
        raise SafeStartError("The reviewed extension batch has an invalid identity.")
    store = _reviewed_batch_store(extension_directory)
    try:
        (store / f"{review_id}.json").unlink(missing_ok=True)
        _fsync_directory(store)
    except OSError as exc:
        raise SafeStartError("Blockstead could not remove the reviewed-batch record.") from exc


def cleanup_reviewed_batches(
    extension_directory: Path,
    *,
    now: float | None = None,
) -> list[str]:
    """Remove expired, unusable, and excess private batch records only."""

    if not extension_directory.is_dir() or extension_directory.is_symlink():
        return []
    store = extension_directory / REVIEWED_BATCH_DIRECTORY
    if not store.exists():
        return []
    if store.is_symlink() or not store.is_dir():
        raise SafeStartError("The reviewed-batch record folder is not safe.")
    current = time.time() if now is None else now
    retained: list[tuple[float, Path]] = []
    removed: list[str] = []
    for path in store.iterdir():
        if (
            path.is_symlink()
            or not path.is_file()
            or not re.fullmatch(r"[0-9a-f]{16}\.json", path.name)
        ):
            continue
        usable = True
        created_at = 0.0
        try:
            batch = ReviewedExtensionBatch.model_validate_json(
                path.read_text(encoding="utf-8")
            )
            created_at = float(batch.created_at)
            if path.stem != batch.review_id:
                usable = False
            elif current - created_at > REVIEWED_BATCH_RETENTION_SECONDS:
                usable = False
            else:
                _verify_batch(extension_directory, batch)
        except (OSError, ValueError, SafeStartError):
            usable = False
        if usable:
            retained.append((created_at, path))
            continue
        try:
            path.unlink()
            removed.append(path.stem)
        except OSError:
            continue
    retained.sort(key=lambda item: item[0], reverse=True)
    for _, path in retained[REVIEWED_BATCH_MAX_RECORDS:]:
        try:
            path.unlink()
            removed.append(path.stem)
        except OSError:
            continue
    if removed:
        _fsync_directory(store)
    return sorted(removed)


def cleanup_validation_workspaces(
    server_directory: Path,
    *,
    now: float | None = None,
) -> list[str]:
    """Remove abandoned disposable clones for exactly one known profile."""

    if server_directory.is_symlink() or not server_directory.is_dir():
        return []
    current = time.time() if now is None else now
    pattern = re.compile(
        rf"^\.{re.escape(server_directory.name)}\.blockstead-validation-[0-9a-f]{{16}}$"
    )
    removed: list[str] = []
    for candidate in server_directory.parent.iterdir():
        if not pattern.fullmatch(candidate.name):
            continue
        try:
            if (
                candidate.is_symlink()
                or not candidate.is_dir()
                or current - candidate.stat().st_mtime
                <= VALIDATION_WORKSPACE_RETENTION_SECONDS
            ):
                continue
            shutil.rmtree(candidate)
            removed.append(candidate.name)
        except OSError:
            continue
    return sorted(removed)


def plan_safe_test_start(
    *,
    profile_id: str,
    distribution: str,
    server_directory: Path,
    process_state: ProcessState | str,
    java_executable: str = "java",
    reviewed_batch: ReviewedExtensionBatch | None = None,
    arguments: tuple[str, ...] | None = None,
    validation_id: str | None = None,
) -> SafeStartPlan:
    """Build a private validation launch plan without mutating the profile."""

    state = process_state.value if isinstance(process_state, ProcessState) else process_state
    if state not in {ProcessState.STOPPED.value, ProcessState.CRASHED.value}:
        raise SafeStartError("Stop the Minecraft server before running a private validation.")
    info = DISTRIBUTIONS.get(distribution)
    if info is None or info.extension_directory is None:
        raise SafeStartError("Private validation is available for recognized modded profiles.")
    if server_directory.is_symlink() or not server_directory.is_dir():
        raise SafeStartError("The profile folder is not safe or is no longer available.")
    if not _eula_accepted(server_directory):
        raise SafeStartError("Accept the Minecraft EULA before running a private validation.")
    if reviewed_batch is not None:
        if reviewed_batch.destination != info.extension_directory:
            raise SafeStartError("The reviewed batch belongs to a different loader type.")
        # Re-identify every file at plan time. Applying the plan rechecks it
        # again immediately before launch and before quarantine.
        _verify_batch(server_directory / info.extension_directory, reviewed_batch)
    try:
        if arguments is None:
            launch_arguments(distribution, server_directory, java_executable)
    except LaunchPlanError as exc:
        raise SafeStartError(str(exc)) from exc
    nonce = validation_id or secrets.token_hex(8)
    if not re.fullmatch(r"[0-9a-f]{16}", nonce):
        raise SafeStartError("The validation plan has an invalid identity.")
    world_name = f"{VALIDATION_WORLD_PREFIX}{nonce}"
    validation_directory = server_directory.parent / (
        f".{server_directory.name}.blockstead-validation-{nonce}"
    )
    if validation_directory.exists() or validation_directory.is_symlink():
        raise SafeStartError(
            "A private validation workspace with this identity already exists."
        )
    return SafeStartPlan(
        profile_id=profile_id,
        distribution=distribution,
        server_directory=str(server_directory),
        validation_directory=str(validation_directory),
        java_executable=java_executable,
        arguments=list(arguments) if arguments is not None else None,
        validation_owner=f"validation:{profile_id}:{nonce}",
        validation_world=world_name,
        private_overrides={
            "level-name": world_name,
            "server-ip": "127.0.0.1",
            "server-port": "0",
            "enable-query": "false",
            "enable-rcon": "false",
            "enable-status": "false",
            "white-list": "true",
            "enforce-whitelist": "true",
            "max-players": "1",
        },
        reviewed_batch=reviewed_batch,
    )


def _verify_batch(
    extension_directory: Path, batch: ReviewedExtensionBatch
) -> list[Path]:
    directory = ensure_managed_directory(extension_directory)
    if directory.name != batch.destination:
        raise SafeStartError("The reviewed batch belongs to another loadout.")
    seen: set[str] = set()
    verified: list[Path] = []
    for item in batch.files:
        if item.file_name in seen or not JAR_NAME_PATTERN.fullmatch(item.file_name):
            raise SafeStartError("The reviewed extension batch contains an unsafe duplicate.")
        seen.add(item.file_name)
        path = directory / item.file_name
        if path.is_symlink() or not path.is_file():
            raise SafeStartError(
                f"{item.file_name} is no longer installed in the reviewed loadout."
            )
        if _sha256(path) != item.sha256:
            raise SafeStartError(f"{item.file_name} changed after its installation review.")
        verified.append(path)
    return verified


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def quarantine_reviewed_batch(
    extension_directory: Path, batch: ReviewedExtensionBatch
) -> QuarantineResult:
    """Atomically disable exactly one reviewed batch, with rollback on failure."""

    try:
        live_files = _verify_batch(extension_directory, batch)
        disabled = ensure_managed_directory(
            disabled_directory(extension_directory), create=True
        )
        collisions = [
            path.name
            for path in live_files
            if (disabled / path.name).exists() or (disabled / path.name).is_symlink()
        ]
        if collisions:
            raise SafeStartError(
                f"{collisions[0]} already exists in the disabled extension folder."
            )
    except (ExtensionOpsError, SafeStartError) as exc:
        return QuarantineResult(
            attempted=True,
            succeeded=False,
            destination=disabled_directory(extension_directory).name,
            detail=str(exc),
        )

    moved: list[str] = []
    try:
        for source in sorted(live_files, key=lambda path: path.name.casefold()):
            os.replace(source, disabled / source.name)
            moved.append(source.name)
        _fsync_directory(extension_directory)
        _fsync_directory(disabled)
    except OSError:
        rollback_failed = False
        for name in reversed(moved):
            try:
                os.replace(disabled / name, extension_directory / name)
            except OSError:
                rollback_failed = True
        _fsync_directory(extension_directory)
        _fsync_directory(disabled)
        detail = (
            "Blockstead could not quarantine the reviewed batch or fully restore it. "
            "Leave the server stopped and inspect both extension folders."
            if rollback_failed
            else (
                "Blockstead could not quarantine the reviewed batch; "
                "the live loadout was restored."
            )
        )
        return QuarantineResult(
            attempted=True,
            succeeded=False,
            destination=disabled.name,
            detail=detail,
        )
    return QuarantineResult(
        attempted=True,
        succeeded=True,
        destination=disabled.name,
        files=moved,
        detail="The reviewed batch was disabled as one transaction.",
    )


class _PropertiesSnapshot:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.existed = False
        self.content = b""
        self.mode = 0o644

    def apply(self, overrides: dict[str, str]) -> None:
        if self.path.is_symlink():
            raise SafeStartError("server.properties cannot be a symbolic link.")
        if self.path.exists() and not self.path.is_file():
            raise SafeStartError("server.properties is not a regular file.")
        try:
            if self.path.is_file():
                self.existed = True
                details = self.path.stat()
                if details.st_size > MAX_PROPERTIES_BYTES:
                    raise SafeStartError("server.properties is too large to validate safely.")
                self.content = self.path.read_bytes()
                self.mode = stat.S_IMODE(details.st_mode)
            suffix = b"" if not self.content or self.content.endswith((b"\n", b"\r")) else b"\n"
            private = "".join(f"{key}={value}\n" for key, value in overrides.items()).encode(
                "ascii"
            )
            self._replace(self.content + suffix + private, self.mode)
        except OSError as exc:
            raise SafeStartError(
                "Blockstead could not apply private validation settings."
            ) from exc

    def restore(self) -> None:
        try:
            if self.existed:
                self._replace(self.content, self.mode)
            else:
                self.path.unlink(missing_ok=True)
                _fsync_directory(self.path.parent)
        except OSError as exc:
            raise SafeStartError(
                "Blockstead could not restore server.properties after validation."
            ) from exc

    def _replace(self, content: bytes, mode: int) -> None:
        staging = self.path.with_name(f".{self.path.name}.validation-{secrets.token_hex(8)}")
        try:
            with staging.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            staging.chmod(mode)
            os.replace(staging, self.path)
            _fsync_directory(self.path.parent)
        finally:
            staging.unlink(missing_ok=True)


def _validation_world_names(world_name: str) -> tuple[str, str, str]:
    return world_name, f"{world_name}_nether", f"{world_name}_the_end"


def _level_name(directory: Path) -> str:
    path = directory / "server.properties"
    try:
        raw = path.read_text(encoding="iso-8859-1") if path.is_file() else ""
    except OSError as exc:
        raise SafeStartError("Blockstead could not read the configured world name.") from exc
    value = "world"
    for line in raw.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith(("#", "!")) or "=" not in candidate:
            continue
        key, setting = candidate.split("=", 1)
        if key.strip() == "level-name":
            value = setting.strip()
    if (
        not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or value.startswith(".")
    ):
        raise SafeStartError("The configured world folder name is not safe to validate.")
    return value


def _prepare_validation_workspace(plan: SafeStartPlan) -> Path:
    """Clone launch/config/loadout files while excluding every live world."""

    source = Path(plan.server_directory)
    target = Path(plan.validation_directory)
    if (
        source.is_symlink()
        or not source.is_dir()
        or target.parent != source.parent
        or target.exists()
        or target.is_symlink()
    ):
        raise SafeStartError("The private validation workspace is not safe to create.")
    level_name = _level_name(source)
    excluded = {
        level_name,
        f"{level_name}_nether",
        f"{level_name}_the_end",
        "backups",
        "logs",
        "crash-reports",
        "mods-disabled",
        "plugins-disabled",
    }

    # shutil.copytree follows source links when symlinks=False. Refuse links in
    # everything that will be copied so a plugin cannot pull outside data into
    # the disposable workspace.
    for child in source.iterdir():
        if child.name in excluded or child.name.startswith(".blockstead"):
            continue
        if child.is_symlink():
            raise SafeStartError(
                f"{child.name} is a symbolic link and cannot be privately validated."
            )
        if child.is_dir() and any(path.is_symlink() for path in child.rglob("*")):
            raise SafeStartError(
                f"{child.name} contains a symbolic link and cannot be privately validated."
            )

    def ignore(directory: str, names: list[str]) -> list[str]:
        if Path(directory) != source:
            return []
        return [
            name
            for name in names
            if name in excluded or name.startswith(".blockstead")
        ]

    try:
        shutil.copytree(source, target, symlinks=False, ignore=ignore)
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise SafeStartError(
            "Blockstead could not create the disposable validation workspace."
        ) from exc
    return target


def _remove_validation_worlds(directory: Path, world_name: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    clean = True
    for name in _validation_world_names(world_name):
        candidate = directory / name
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            clean = False
            warnings.append(
                f"The private validation path {name} was not a normal folder and was left in place."
            )
            continue
        try:
            shutil.rmtree(candidate)
        except OSError:
            clean = False
            warnings.append(
                f"Blockstead could not remove the disposable validation world {name}."
            )
    return clean, warnings


def _remove_validation_workspace(directory: Path) -> tuple[bool, str | None]:
    if not directory.exists() and not directory.is_symlink():
        return True, None
    if directory.is_symlink() or not directory.is_dir():
        return (
            False,
            "The private validation workspace became unsafe and was left in place.",
        )
    try:
        shutil.rmtree(directory)
    except OSError:
        return (
            False,
            "Blockstead could not remove the disposable validation workspace.",
        )
    return True, None


def _bounded_evidence(
    events: list[LogEvent], max_lines: int, max_characters: int
) -> tuple[list[StartupEvidence], bool]:
    selected: list[LogEvent] = []
    characters = 0
    truncated = False
    for event in reversed(events):
        cost = len(event.line)
        if len(selected) >= max_lines or characters + cost > max_characters:
            truncated = True
            break
        selected.append(event)
        characters += cost
    selected.reverse()
    return (
        [
            StartupEvidence(
                sequence=event.sequence,
                timestamp=event.timestamp,
                line=event.line,
            )
            for event in selected
        ],
        truncated,
    )


def _failure_from_logs(lines: Iterable[str]) -> FailureKind:
    joined = "\n".join(lines)
    if any(pattern.search(joined) for pattern in _EXTENSION_FAILURE_MARKERS):
        return "extension_error"
    if any(pattern.search(joined) for pattern in _JAVA_FAILURE_MARKERS):
        return "java_error"
    return "startup_crash"


async def _wait_until_ready_or_stopped(
    manager: ProcessManager, ready_limit: float
) -> ProcessState:
    async def poll() -> ProcessState:
        while manager.state in {ProcessState.STARTING, ProcessState.STOPPING}:  # noqa: ASYNC110
            await asyncio.sleep(0.05)
        return manager.state

    return await asyncio.wait_for(poll(), ready_limit)


async def _stop_validation(manager: ProcessManager, stop_limit: float) -> None:
    if manager.state in {ProcessState.RUNNING, ProcessState.STARTING, ProcessState.DEGRADED}:
        if not await manager.stop(stop_limit):
            await manager.force_stop()
    elif manager.state == ProcessState.STOPPING:
        process = getattr(manager, "_process", None)
        if process is not None and process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), stop_limit)
            except TimeoutError:
                await manager.force_stop()


async def run_safe_test_start(
    manager: ProcessManager,
    plan: SafeStartPlan,
    *,
    ready_timeout: float = DEFAULT_READY_TIMEOUT_SECONDS,
    stop_timeout: float = DEFAULT_STOP_TIMEOUT_SECONDS,
    max_evidence_lines: int = DEFAULT_EVIDENCE_LINES,
    max_evidence_characters: int = DEFAULT_EVIDENCE_CHARACTERS,
) -> SafeStartResult:
    """Run a private startup test and quarantine a failed reviewed batch."""

    if ready_timeout <= 0 or stop_timeout <= 0:
        raise SafeStartError("Validation timeouts must be greater than zero.")
    if max_evidence_lines < 1 or max_evidence_characters < 1:
        raise SafeStartError("Validation evidence limits must be greater than zero.")
    if manager.state not in {ProcessState.STOPPED, ProcessState.CRASHED}:
        raise SafeStartError("Stop the Minecraft server before running a private validation.")

    directory = Path(plan.server_directory)
    info = DISTRIBUTIONS.get(plan.distribution)
    if (
        directory.is_symlink()
        or not directory.is_dir()
        or info is None
        or info.extension_directory is None
    ):
        raise SafeStartError("The private validation plan no longer matches this profile.")
    extension_directory = directory / info.extension_directory
    if plan.reviewed_batch is not None:
        _verify_batch(extension_directory, plan.reviewed_batch)
    started = time.monotonic()
    baseline = max((event.sequence for event in manager.logs()), default=0)
    ready = False
    timed_out = False
    launch_error: str | None = None
    properties_restored = False
    cleanup_warnings: list[str] = []
    validation_world_removed = True
    validation_workspace_removed = False
    validation_directory = _prepare_validation_workspace(plan)
    properties = _PropertiesSnapshot(validation_directory / "server.properties")
    properties_applied = False
    try:
        try:
            command = (
                tuple(plan.arguments)
                if plan.arguments is not None
                else launch_arguments(
                    plan.distribution,
                    validation_directory,
                    plan.java_executable,
                )
            )
            properties.apply(plan.private_overrides)
            properties_applied = True
            await manager.start(
                command,
                cwd=validation_directory,
                label="Private validation",
                owner=plan.validation_owner,
            )
            try:
                terminal = await _wait_until_ready_or_stopped(manager, ready_timeout)
                ready = terminal == ProcessState.RUNNING
            except TimeoutError:
                timed_out = True
        except (InvalidTransition, LaunchPlanError, OSError, ValueError) as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                await _stop_validation(manager, stop_timeout)
            except (InvalidTransition, OSError, TimeoutError) as exc:
                cleanup_warnings.append(
                    f"The validation process did not stop cleanly ({type(exc).__name__})."
                )
    finally:
        if properties_applied:
            try:
                properties.restore()
                properties_restored = True
            except SafeStartError as exc:
                cleanup_warnings.append(str(exc))
        else:
            # No temporary settings were installed, so the clone still exactly
            # matches the source properties.
            properties_restored = True
        validation_world_removed, world_warnings = _remove_validation_worlds(
            validation_directory, plan.validation_world
        )
        cleanup_warnings.extend(world_warnings)
        validation_workspace_removed, workspace_warning = _remove_validation_workspace(
            validation_directory
        )
        if workspace_warning:
            cleanup_warnings.append(workspace_warning)

    run_events = [
        event
        for event in manager.logs()
        if event.sequence > baseline and event.profile_id == plan.validation_owner
    ]
    evidence, evidence_truncated = _bounded_evidence(
        run_events, max_evidence_lines, max_evidence_characters
    )
    failure_kind: FailureKind | None = None
    if launch_error is not None:
        failure_kind = "launch_error"
    elif timed_out:
        failure_kind = "startup_timeout"
    elif not ready:
        failure_kind = _failure_from_logs(event.line for event in run_events)
    elif (
        not properties_restored
        or not validation_world_removed
        or not validation_workspace_removed
        or cleanup_warnings
    ):
        failure_kind = "cleanup_error"

    status: ValidationStatus = "passed" if failure_kind is None else "failed"
    if failure_kind == "launch_error":
        detail = "The private validation process could not start."
    elif failure_kind == "startup_timeout":
        detail = "The server did not report ready before the private validation timeout."
    elif failure_kind == "extension_error":
        detail = "Startup evidence points to an incompatible or incomplete extension loadout."
    elif failure_kind == "java_error":
        detail = "Startup evidence points to a Java or launch-runtime problem."
    elif failure_kind == "startup_crash":
        detail = "The server exited before reporting that it was ready."
    elif failure_kind == "cleanup_error":
        detail = "The server started, but Blockstead could not fully clean up validation state."
    else:
        detail = "The server reported ready privately and shut down cleanly."

    quarantine = QuarantineResult(attempted=False, succeeded=False)
    # A timeout, Java failure, or generic launch crash does not prove that the
    # reviewed jars caused the problem. Quarantine only when bounded startup
    # evidence explicitly matches an extension compatibility/dependency error.
    if failure_kind == "extension_error" and plan.reviewed_batch is not None:
        quarantine = quarantine_reviewed_batch(
            extension_directory, plan.reviewed_batch
        )
        if not quarantine.succeeded and quarantine.detail:
            cleanup_warnings.append(quarantine.detail)

    return SafeStartResult(
        profile_id=plan.profile_id,
        status=status,
        failure_kind=failure_kind,
        detail=detail,
        ready=ready,
        exit_code=manager.exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        evidence=evidence,
        evidence_truncated=evidence_truncated,
        properties_restored=properties_restored,
        validation_world_removed=validation_world_removed,
        validation_workspace_removed=validation_workspace_removed,
        quarantine=quarantine,
        warnings=cleanup_warnings,
    )
