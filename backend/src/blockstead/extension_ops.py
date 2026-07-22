"""Safe file operations for managed plugin and mod directories.

Every mutation stays inside the profile's managed extension directories. New
files are staged, verified by their caller, and promoted as a small
transaction. When a multi-file promotion fails, the previous loadout is put
back before an error is returned. This matters for updates: a new root jar and
newly required dependencies must never be left half-installed.
"""

import hashlib
import os
import secrets
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path

from .modrinth import JAR_NAME_PATTERN

MAX_UPLOAD_BYTES = 128 * 1024 * 1024
SUPPORTED_CHECKSUMS = frozenset({"sha1", "sha256", "sha512"})


class ExtensionOpsError(ValueError):
    """The requested file operation was refused; message is user-safe."""


def disabled_directory(extension_directory: Path) -> Path:
    return extension_directory.with_name(extension_directory.name + "-disabled")


def ensure_managed_directory(directory: Path, *, create: bool = False) -> Path:
    """Confirm a managed directory is real, never a symlink to somewhere else."""
    if directory.is_symlink():
        raise ExtensionOpsError("The managed extensions folder cannot be a symbolic link.")
    if directory.exists() and not directory.is_dir():
        raise ExtensionOpsError("The managed extensions path is not a folder.")
    if create:
        directory.mkdir(mode=0o755, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ExtensionOpsError("The managed extensions folder is not safe to use.")
    return directory


def _managed_disabled_directory(extension_directory: Path, *, create: bool = False) -> Path:
    return ensure_managed_directory(disabled_directory(extension_directory), create=create)


def _validated_jar(directory: Path, file_name: str) -> Path:
    if not JAR_NAME_PATTERN.match(file_name):
        raise ExtensionOpsError("That file name is not an acceptable jar name.")
    path = directory / file_name
    if path.parent != directory or path.is_symlink() or not path.is_file():
        raise ExtensionOpsError("That file was not found in the managed folder.")
    return path


def checksum_matches(path: Path, algorithm: str, expected: str) -> bool:
    """Compare a regular managed file with a catalog's published digest."""
    if algorithm not in SUPPORTED_CHECKSUMS:
        raise ExtensionOpsError("The catalog used an unsupported file checksum.")
    if path.is_symlink() or not path.is_file():
        raise ExtensionOpsError("A managed extension file was replaced by an unsafe path.")
    digest = hashlib.new(algorithm)
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ExtensionOpsError("Blockstead could not verify an existing extension file.") from exc
    return digest.hexdigest().casefold() == expected.casefold()


def create_staging_directory(extension_directory: Path) -> Path:
    """Create a private, same-filesystem staging directory for an install."""
    directory = ensure_managed_directory(extension_directory, create=True)
    staging = directory / f".blockstead-install-{secrets.token_hex(8)}"
    try:
        staging.mkdir(mode=0o700)
    except OSError as exc:
        raise ExtensionOpsError(
            "Blockstead could not prepare a safe extension staging area."
        ) from exc
    return staging


def _fsync_directory(directory: Path) -> None:
    """Persist directory entry changes where the platform supports it."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystem types do not support directory fsync. The rename
        # transaction is still safe in-process, so do not make it destructive.
        pass
    finally:
        os.close(descriptor)


def _remove_staging(staging: Path) -> None:
    try:
        shutil.rmtree(staging)
    except OSError as exc:
        raise ExtensionOpsError(
            "The extension change completed, but Blockstead could not remove its private "
            "staging files. Leave the server stopped and try the change again."
        ) from exc


def promote_staged_files(
    extension_directory: Path,
    staging: Path,
    file_names: Iterable[str],
    *,
    retire_names: Iterable[str] = (),
    expected_retired_checksums: dict[str, tuple[str, str]] | None = None,
) -> None:
    """Promote staged jars and retire replacements with rollback on failure.

    ``retire_names`` are old live files that an update replaces. They are moved
    to the private staging folder first rather than deleted. If any later
    promotion fails, new files are removed and every retired file is restored.
    On success the private folder (and only that folder) is removed, safely
    cleaning up old releases.
    """
    directory = ensure_managed_directory(extension_directory, create=True)
    if staging.parent != directory or staging.is_symlink() or not staging.is_dir():
        raise ExtensionOpsError("The extension staging area is not safe to use.")

    names = list(file_names)
    retired = list(retire_names)
    if not names:
        raise ExtensionOpsError("The catalog did not provide any extension files to install.")
    if len(names) != len(set(names)) or len(retired) != len(set(retired)):
        raise ExtensionOpsError("The extension change contains duplicate file names.")
    for name in [*names, *retired]:
        if not JAR_NAME_PATTERN.match(name):
            raise ExtensionOpsError("The extension change contains an unsafe jar name.")

    expected = expected_retired_checksums or {}
    if set(expected) - set(retired):
        raise ExtensionOpsError("The extension change has an invalid replacement check.")

    rollback = staging / ".rollback"
    moved_old: list[str] = []
    promoted: list[str] = []
    originals = set(retired)
    # A same-name update replaces its target; a renamed update retires the old
    # name and promotes a new one. An unexpected target appearing after the
    # caller's collision check is a concurrent modification, not permission to
    # overwrite someone else's jar.
    unexpected = [
        name
        for name in names
        if name not in originals
        and ((directory / name).exists() or (directory / name).is_symlink())
    ]
    if unexpected:
        raise ExtensionOpsError(
            f"A file named {unexpected[0]} was installed while this change was in progress."
        )
    try:
        for name in names:
            _validated_jar(staging, name)
        for name in originals:
            source = directory / name
            if source.is_symlink() or not source.is_file():
                raise ExtensionOpsError("A managed extension file changed before installation.")
            if name in expected:
                algorithm, digest = expected[name]
                if not checksum_matches(source, algorithm, digest):
                    raise ExtensionOpsError(
                        "The extension selected for update changed before Blockstead could "
                        "replace it. Nothing was changed."
                    )

        rollback.mkdir(mode=0o700)
        for name in sorted(originals):
            os.replace(directory / name, rollback / name)
            moved_old.append(name)
        for name in names:
            os.replace(staging / name, directory / name)
            promoted.append(name)
        _fsync_directory(directory)
    except (OSError, ExtensionOpsError) as exc:
        rollback_error = False
        for name in reversed(promoted):
            try:
                (directory / name).unlink(missing_ok=True)
            except OSError:
                rollback_error = True
        for name in reversed(moved_old):
            try:
                os.replace(rollback / name, directory / name)
            except OSError:
                rollback_error = True
        _fsync_directory(directory)
        if rollback_error:
            raise ExtensionOpsError(
                "Blockstead could not finish the extension change or fully restore the "
                "previous loadout. Leave the server stopped and check the extension folder."
            ) from exc
        if isinstance(exc, ExtensionOpsError):
            raise exc
        raise ExtensionOpsError(
            "Blockstead could not activate the verified extension files. Your previous "
            "loadout was restored."
        ) from exc

    _remove_staging(staging)


def set_enabled(extension_directory: Path, file_name: str, enabled: bool) -> Path:
    """Move one jar between the live directory and the managed disabled directory."""
    live = ensure_managed_directory(extension_directory)
    disabled = _managed_disabled_directory(extension_directory)
    source_dir, target_dir = (disabled, live) if enabled else (live, disabled)
    source = _validated_jar(source_dir, file_name)
    ensure_managed_directory(target_dir, create=True)
    target = target_dir / file_name
    if target.exists() or target.is_symlink():
        raise ExtensionOpsError("A file with that name already exists in the target folder.")
    os.replace(source, target)
    _fsync_directory(target_dir)
    return target


def set_all_enabled(extension_directory: Path, enabled: bool) -> tuple[list[str], list[str]]:
    """Move every managed jar between the live and disabled directories.

    Returns (moved, skipped). A jar is skipped — never overwritten or renamed
    — when the target already has a file with its name, or when its name fails
    the same validation used for single-file operations.
    """
    live = ensure_managed_directory(extension_directory)
    disabled_dir = _managed_disabled_directory(extension_directory)
    source_dir, target_dir = (disabled_dir, live) if enabled else (live, disabled_dir)
    if not source_dir.is_dir():
        return [], []
    moved: list[str] = []
    skipped: list[str] = []
    jars = sorted(
        entry.name
        for entry in source_dir.iterdir()
        if entry.suffix == ".jar" and entry.is_file() and not entry.is_symlink()
    )
    if jars:
        ensure_managed_directory(target_dir, create=True)
    for name in jars:
        target = target_dir / name
        if not JAR_NAME_PATTERN.match(name) or target.exists() or target.is_symlink():
            skipped.append(name)
            continue
        os.replace(source_dir / name, target_dir / name)
        moved.append(name)
    if moved:
        _fsync_directory(source_dir)
        _fsync_directory(target_dir)
    return moved, skipped


def remove(extension_directory: Path, file_name: str, disabled: bool = False) -> None:
    """Delete one validated jar from the live or disabled managed directory."""
    directory = (
        _managed_disabled_directory(extension_directory)
        if disabled
        else ensure_managed_directory(extension_directory)
    )
    _validated_jar(directory, file_name).unlink()
    _fsync_directory(directory)


def place_upload(extension_directory: Path, file_name: str, content: bytes) -> Path:
    """Validate an uploaded jar, then place it atomically in the live directory."""
    if not JAR_NAME_PATTERN.match(file_name):
        raise ExtensionOpsError(
            "Upload a .jar file whose name uses only letters, digits, dots, "
            "spaces, hyphens, and underscores."
        )
    if len(content) > MAX_UPLOAD_BYTES:
        raise ExtensionOpsError("The uploaded file is larger than Blockstead accepts.")
    if not content:
        raise ExtensionOpsError("The uploaded file was empty.")
    directory = ensure_managed_directory(extension_directory, create=True)
    disabled = _managed_disabled_directory(extension_directory)
    target = directory / file_name
    disabled_target = disabled / file_name
    if (
        target.exists()
        or target.is_symlink()
        or disabled_target.exists()
        or disabled_target.is_symlink()
    ):
        raise ExtensionOpsError("A file with that name is already installed.")
    staging = directory / f".{file_name}.part"
    try:
        with staging.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if not zipfile.is_zipfile(staging):
            raise ExtensionOpsError("The uploaded file is not a valid jar archive.")
        os.replace(staging, target)
        _fsync_directory(directory)
    except OSError as exc:
        raise ExtensionOpsError("Blockstead could not safely place the uploaded jar.") from exc
    finally:
        staging.unlink(missing_ok=True)
    return target
