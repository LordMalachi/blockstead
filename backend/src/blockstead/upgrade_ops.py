"""Transactional launch-artifact upgrades with an explicit recovery path.

Vanilla, Paper, and Fabric all launch through one top-level jar.  That makes a
bounded in-place upgrade possible: download the replacement into a private
same-filesystem staging directory, copy and verify the prior launch jar in
Blockstead's private recovery store, promote the replacement atomically, and
validate the launch plan before reporting success.  Recovery storage may be on
a different filesystem, so active launch files are never moved directly into
or out of it.

World folders are never part of this rollback.  Downgrading a launch artifact
after a newer server has opened a world can be unsafe, so recovery remains an
explicit owner action and the API describes that boundary plainly.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .distributions import LaunchPlanError, launch_arguments
from .host_fs import (
    atomic_write_text,
    describe_os_error,
    fsync_path,
    restrict_to_owner,
    rmtree,
)

DIRECT_UPGRADE_DISTRIBUTIONS = frozenset({"vanilla", "paper", "fabric"})
RECOVERY_ID_LENGTH = 24


class UpgradeOperationError(RuntimeError):
    """A launch upgrade was refused or failed; messages are safe to show."""


@dataclass(frozen=True)
class UpgradeRecovery:
    recovery_id: str
    recovery_directory: Path
    launch_file: str
    previous_version: str | None
    new_version: str
    previous_loader_version: str | None
    new_loader_version: str | None
    previous_paper_build: int | None = None
    new_paper_build: int | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _failure_detail(exc: BaseException, path: Path) -> str:
    if isinstance(exc, OSError):
        return describe_os_error(exc, path)
    return str(exc)


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    description: str,
) -> str:
    """Copy a file through a destination-local temp and verify the installed copy.

    ``os.replace`` is only used between paths in ``destination.parent``.  That
    keeps the final rename atomic even when ``source`` lives on a different
    filesystem.  The source digest is calculated while copying and compared
    with a fresh digest after the destination has been flushed and renamed.
    """

    if destination.exists() or destination.is_symlink():
        raise UpgradeOperationError(
            f"Blockstead found an existing file where it needs to place the {description}."
        )
    source_digest = hashlib.sha256()
    temporary: Path | None = None
    installed = False
    verified = False
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=".blockstead-copy-",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as target:
            with source.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    source_digest.update(chunk)
                    target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        restrict_to_owner(temporary)
        os.replace(temporary, destination)
        temporary = None
        installed = True
        fsync_path(destination)
        expected_digest = source_digest.hexdigest()
        if _sha256(destination) != expected_digest:
            raise UpgradeOperationError(
                f"Blockstead could not verify the copied {description}; the launch-file "
                "change was not activated."
            )
        verified = True
        return expected_digest
    except UpgradeOperationError:
        raise
    except OSError as exc:
        raise UpgradeOperationError(
            f"Blockstead could not create and flush the {description} from {source} "
            f"to {destination}. {_failure_detail(exc, destination)}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        if installed and not verified:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass


def active_launch_file(distribution: str, server_directory: Path) -> Path:
    """Return the one directly replaceable launch jar for a supported profile."""

    if distribution not in DIRECT_UPGRADE_DISTRIBUTIONS:
        raise UpgradeOperationError(
            "This server uses a multi-file loader installer, so Blockstead cannot "
            "replace it through the bounded launch-file upgrade path."
        )
    try:
        arguments = launch_arguments(distribution, server_directory)
    except LaunchPlanError as exc:
        raise UpgradeOperationError(str(exc)) from exc
    try:
        jar_index = arguments.index("-jar") + 1
        launch = Path(arguments[jar_index])
    except (ValueError, IndexError) as exc:
        raise UpgradeOperationError(
            "Blockstead could not identify this server's active launch file."
        ) from exc
    if not launch.is_absolute():
        launch = server_directory / launch
    try:
        if launch.parent.resolve(strict=True) != server_directory.resolve(strict=True):
            raise UpgradeOperationError(
                "The active launch file is outside the server folder and will not be replaced."
            )
    except OSError as exc:
        raise UpgradeOperationError("The active launch file could not be checked.") from exc
    if launch.is_symlink() or not launch.is_file() or launch.suffix.casefold() != ".jar":
        raise UpgradeOperationError("The active launch file is not a regular server jar.")
    return launch


def create_upgrade_staging(server_directory: Path) -> Path:
    if server_directory.is_symlink() or not server_directory.is_dir():
        raise UpgradeOperationError("The server folder is not safe to upgrade.")
    staging = server_directory / f".blockstead-upgrade-{secrets.token_hex(8)}"
    try:
        staging.mkdir(mode=0o700)
    except OSError as exc:
        raise UpgradeOperationError(
            "Blockstead could not prepare a private upgrade staging area."
        ) from exc
    return staging


def _validate_fabric_launcher(path: Path) -> None:
    """Reject an HTML/error response masquerading as a Fabric launcher JAR.

    Fabric's launcher endpoint does not provide a publisher checksum. Keep the
    check bounded: validate the ZIP container and read one regular entry so a
    truncated or non-archive response cannot reach the atomic replacement.
    """

    try:
        if not zipfile.is_zipfile(path):
            raise UpgradeOperationError(
                "The downloaded Fabric launcher is not a valid JAR archive."
            )
        with zipfile.ZipFile(path) as archive:
            member = next((entry for entry in archive.infolist() if not entry.is_dir()), None)
            if member is None:
                raise UpgradeOperationError(
                    "The downloaded Fabric launcher archive has no readable entries."
                )
            with archive.open(member) as handle:
                handle.read(1)
    except UpgradeOperationError:
        raise
    except (
        OSError,
        EOFError,
        KeyError,
        NotImplementedError,
        RuntimeError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        zlib.error,
    ) as exc:
        raise UpgradeOperationError(
            "The downloaded Fabric launcher is not a readable JAR archive."
        ) from exc


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    try:
        atomic_write_text(
            path,
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            before_replace=restrict_to_owner,
        )
    except OSError as exc:
        raise UpgradeOperationError(
            "Blockstead could not record the launch-file recovery instructions. "
            f"{describe_os_error(exc, path)}"
        ) from exc


def promote_launch_upgrade(
    *,
    server_directory: Path,
    distribution: str,
    staged_file: Path,
    recovery_root: Path,
    profile_id: str,
    previous_version: str | None,
    new_version: str,
    previous_loader_version: str | None,
    new_loader_version: str | None,
    previous_paper_build: int | None = None,
    new_paper_build: int | None = None,
) -> UpgradeRecovery:
    """Copy the prior jar to recovery, then atomically replace the active jar."""

    active = active_launch_file(distribution, server_directory)
    if (
        staged_file.parent.parent != server_directory
        or not staged_file.parent.name.startswith(".blockstead-upgrade-")
        or staged_file.is_symlink()
        or not staged_file.is_file()
    ):
        raise UpgradeOperationError("The staged launch file is not safe to promote.")
    if distribution == "fabric":
        _validate_fabric_launcher(staged_file)

    recovery_id = secrets.token_hex(RECOVERY_ID_LENGTH // 2)
    recovery_directory = recovery_root / "server-upgrades" / profile_id / recovery_id
    previous = recovery_directory / active.name
    replacement = staged_file.parent / active.name
    server_displaced = server_directory / f".blockstead-r-{recovery_id}-d"
    if server_displaced.exists() or server_displaced.is_symlink():
        raise UpgradeOperationError(
            "The server folder contains an unfinished launch-file recovery and cannot "
            "be reused."
        )
    if staged_file != replacement:
        try:
            os.replace(staged_file, replacement)
        except OSError as exc:
            raise UpgradeOperationError(
                "Blockstead could not prepare the replacement launch file. "
                f"{describe_os_error(exc, replacement)}"
            ) from exc

    try:
        recovery_directory.mkdir(parents=True)
        restrict_to_owner(recovery_directory)
    except OSError as exc:
        raise UpgradeOperationError(describe_os_error(exc, recovery_directory)) from exc

    active_displaced = False
    failure_path = recovery_directory
    try:
        previous_digest = _copy_verified(
            active,
            previous,
            description="prior launch file in recovery storage",
        )
        failure_path = active
        if _sha256(active) != previous_digest:
            raise UpgradeOperationError(
                "The active launch file changed while its recovery copy was being "
                "prepared, so the upgrade was not activated."
            )
        failure_path = server_displaced
        os.replace(active, server_displaced)
        active_displaced = True
        failure_path = active
        os.replace(replacement, active)
        failure_path = server_directory
        launch_arguments(distribution, server_directory)
        failure_path = recovery_directory / "recovery.json"
        _write_manifest(
            recovery_directory / "recovery.json",
            {
                "schema": 1,
                "profile_id": profile_id,
                "distribution": distribution,
                "launch_file": active.name,
                "previous_sha256": previous_digest,
                "new_sha256": _sha256(active),
                "previous_version": previous_version,
                "new_version": new_version,
                "previous_loader_version": previous_loader_version,
                "new_loader_version": new_loader_version,
                "previous_paper_build": previous_paper_build,
                "new_paper_build": new_paper_build,
                "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                "used": False,
            },
        )
    except (OSError, LaunchPlanError, UpgradeOperationError) as exc:
        failure_detail = _failure_detail(exc, failure_path)
        rollback_failed = False
        rollback_detail: str | None = None
        if active_displaced:
            try:
                os.replace(server_displaced, active)
            except OSError as rollback_exc:
                rollback_failed = True
                rollback_detail = _failure_detail(rollback_exc, active)
        if rollback_failed:
            raise UpgradeOperationError(
                "The replacement could not be activated and Blockstead could not fully "
                "restore the prior launch file. The preserved copy remains at "
                f"{recovery_directory}. Leave the server stopped and inspect that "
                f"folder before starting it. Initial failure: {failure_detail} "
                f"Restore failure: {rollback_detail}"
            ) from exc
        # An UpgradeOperationError is raised either way below; removing the
        # never-finalized recovery folder here is tidiness, not correctness.
        try:
            rmtree(recovery_directory)
        except OSError:
            pass
        raise UpgradeOperationError(
            "The replacement could not be activated. The prior launch file was restored. "
            f"Reason: {failure_detail}"
        ) from exc

    try:
        server_displaced.unlink(missing_ok=True)
    except OSError:
        pass

    return UpgradeRecovery(
        recovery_id=recovery_id,
        recovery_directory=recovery_directory,
        launch_file=active.name,
        previous_version=previous_version,
        new_version=new_version,
        previous_loader_version=previous_loader_version,
        new_loader_version=new_loader_version,
        previous_paper_build=previous_paper_build,
        new_paper_build=new_paper_build,
    )


def _read_recovery(
    recovery_root: Path, profile_id: str, recovery_id: str
) -> tuple[Path, dict[str, object]]:
    if (
        len(recovery_id) != RECOVERY_ID_LENGTH
        or not all(character in "0123456789abcdef" for character in recovery_id)
    ):
        raise UpgradeOperationError("That upgrade recovery id is not valid.")
    directory = recovery_root / "server-upgrades" / profile_id / recovery_id
    manifest_path = directory / "recovery.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpgradeOperationError("That upgrade recovery record could not be read.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("profile_id") != profile_id
    ):
        raise UpgradeOperationError("That upgrade recovery record is not usable.")
    return directory, payload


def rollback_launch_upgrade(
    *,
    server_directory: Path,
    recovery_root: Path,
    profile_id: str,
    recovery_id: str,
    distribution: str,
) -> dict[str, object]:
    """Restore the previous jar through server-local staging if unchanged."""

    directory, manifest = _read_recovery(recovery_root, profile_id, recovery_id)
    if manifest.get("used") is True:
        raise UpgradeOperationError("That launch-file recovery has already been used.")
    if manifest.get("distribution") != distribution:
        raise UpgradeOperationError("That recovery belongs to a different server type.")
    launch_name = manifest.get("launch_file")
    current_digest = manifest.get("new_sha256")
    previous_digest = manifest.get("previous_sha256")
    if not all(isinstance(value, str) for value in (launch_name, current_digest, previous_digest)):
        raise UpgradeOperationError("That upgrade recovery record is incomplete.")
    assert isinstance(launch_name, str)
    launch_path = Path(launch_name)
    if (
        not launch_name
        or launch_path.name != launch_name
        or launch_path.parent != Path(".")
        or launch_path.suffix.casefold() != ".jar"
    ):
        raise UpgradeOperationError("That upgrade recovery record has an unsafe launch file.")
    active = server_directory / launch_name
    previous = directory / launch_name
    if (
        active.is_symlink()
        or not active.is_file()
        or previous.is_symlink()
        or not previous.is_file()
    ):
        raise UpgradeOperationError("The current or recovered launch file is no longer available.")
    if _sha256(active) != current_digest:
        raise UpgradeOperationError(
            "The current launch file changed after this upgrade, so Blockstead will not "
            "overwrite it with an older recovery copy."
        )
    if _sha256(previous) != previous_digest:
        raise UpgradeOperationError(
            "The preserved launch file failed verification and will not be restored."
        )

    replaced = directory / f"replaced-{launch_name}"
    rollback_stage = server_directory / f".blockstead-r-{recovery_id}-s"
    server_displaced = server_directory / f".blockstead-r-{recovery_id}-d"
    if (
        rollback_stage.exists()
        or rollback_stage.is_symlink()
        or server_displaced.exists()
        or server_displaced.is_symlink()
        or replaced.exists()
        or replaced.is_symlink()
    ):
        raise UpgradeOperationError(
            "That recovery contains an unfinished restore and cannot be reused."
        )
    active_moved = False
    replacement_snapshot = False
    failure_path = rollback_stage
    try:
        snapshot_digest = _copy_verified(
            active,
            replaced,
            description="current launch file in recovery storage",
        )
        replacement_snapshot = True
        if snapshot_digest != current_digest:
            raise UpgradeOperationError(
                "The current launch file changed while its recovery copy was being "
                "prepared, so the previous file was not restored."
            )
        rollback_digest = _copy_verified(
            previous,
            rollback_stage,
            description="preserved launch file for rollback",
        )
        if rollback_digest != previous_digest:
            raise UpgradeOperationError(
                "The preserved launch file changed while its rollback copy was being "
                "prepared, so the newer file was not replaced."
            )
        failure_path = server_displaced
        os.replace(active, server_displaced)
        active_moved = True
        failure_path = active
        os.replace(rollback_stage, active)
        failure_path = server_directory
        launch_arguments(distribution, server_directory)
        manifest["used"] = True
        manifest["used_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
        failure_path = directory / "recovery.json"
        _write_manifest(directory / "recovery.json", manifest)
    except (OSError, LaunchPlanError, UpgradeOperationError) as exc:
        failure_detail = _failure_detail(exc, failure_path)
        rollback_failed = False
        rollback_detail: str | None = None
        if active_moved:
            try:
                # The recovery source was copied, not moved, so it remains
                # available while the newer server-side copy is restored.
                os.replace(server_displaced, active)
            except OSError as rollback_exc:
                rollback_failed = True
                rollback_detail = _failure_detail(rollback_exc, active)
        if rollback_failed:
            raise UpgradeOperationError(
                "Recovery failed and Blockstead could not fully restore the newer launch "
                f"file. The launch files remain in the server folder and recovery folder "
                f"{directory}. Leave the server stopped and inspect both locations. "
                f"Initial failure: {failure_detail} Restore failure: {rollback_detail}"
            ) from exc
        try:
            rollback_stage.unlink(missing_ok=True)
        except OSError:
            pass
        if replacement_snapshot:
            try:
                replaced.unlink(missing_ok=True)
            except OSError:
                pass
        raise UpgradeOperationError(
            "The previous launch file could not be restored; the newer file remains active. "
            f"Reason: {failure_detail}"
        ) from exc
    try:
        server_displaced.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        previous.unlink(missing_ok=True)
    except OSError:
        pass
    return manifest
