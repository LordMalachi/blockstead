"""Transactional launch-artifact upgrades with an explicit recovery path.

Vanilla, Paper, and Fabric all launch through one top-level jar.  That makes a
bounded in-place upgrade possible: download the replacement into a private
same-filesystem staging directory, move the prior launch jar into Blockstead's
private recovery store, promote the replacement atomically, and validate the
launch plan before reporting success.

World folders are never part of this rollback.  Downgrading a launch artifact
after a newer server has opened a world can be unsafe, so recovery remains an
explicit owner action and the API describes that boundary plainly.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .distributions import LaunchPlanError, launch_arguments

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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.partial")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise UpgradeOperationError(
            "Blockstead could not record the launch-file recovery instructions."
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
) -> UpgradeRecovery:
    """Atomically replace the active launch jar and retain the prior one."""

    active = active_launch_file(distribution, server_directory)
    if (
        staged_file.parent.parent != server_directory
        or not staged_file.parent.name.startswith(".blockstead-upgrade-")
        or staged_file.is_symlink()
        or not staged_file.is_file()
    ):
        raise UpgradeOperationError("The staged launch file is not safe to promote.")

    recovery_id = secrets.token_hex(RECOVERY_ID_LENGTH // 2)
    recovery_directory = recovery_root / "server-upgrades" / profile_id / recovery_id
    previous = recovery_directory / active.name
    replacement = staged_file.parent / active.name
    if staged_file != replacement:
        try:
            os.replace(staged_file, replacement)
        except OSError as exc:
            raise UpgradeOperationError(
                "Blockstead could not prepare the replacement launch file."
            ) from exc

    try:
        recovery_directory.mkdir(parents=True, mode=0o700)
        recovery_directory.chmod(0o700)
    except OSError as exc:
        raise UpgradeOperationError(
            "Blockstead could not prepare the launch-file recovery folder."
        ) from exc

    promoted = False
    try:
        os.replace(active, previous)
        os.replace(replacement, active)
        promoted = True
        launch_arguments(distribution, server_directory)
        _write_manifest(
            recovery_directory / "recovery.json",
            {
                "schema": 1,
                "profile_id": profile_id,
                "distribution": distribution,
                "launch_file": active.name,
                "previous_sha256": _sha256(previous),
                "new_sha256": _sha256(active),
                "previous_version": previous_version,
                "new_version": new_version,
                "previous_loader_version": previous_loader_version,
                "new_loader_version": new_loader_version,
                "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                "used": False,
            },
        )
    except (OSError, LaunchPlanError, UpgradeOperationError) as exc:
        rollback_failed = False
        if promoted:
            try:
                active.unlink(missing_ok=True)
            except OSError:
                rollback_failed = True
        if previous.exists():
            try:
                os.replace(previous, active)
            except OSError:
                rollback_failed = True
        shutil.rmtree(recovery_directory, ignore_errors=True)
        if rollback_failed:
            raise UpgradeOperationError(
                "The replacement could not be activated and Blockstead could not fully "
                "restore the prior launch file. Leave the server stopped and inspect "
                "its folder before starting it."
            ) from exc
        raise UpgradeOperationError(
            "The replacement could not be activated. The prior launch file was restored."
        ) from exc

    return UpgradeRecovery(
        recovery_id=recovery_id,
        recovery_directory=recovery_directory,
        launch_file=active.name,
        previous_version=previous_version,
        new_version=new_version,
        previous_loader_version=previous_loader_version,
        new_loader_version=new_loader_version,
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
    """Restore the previous launch jar if the current replacement is unchanged."""

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

    displaced = directory / f"replaced-{launch_name}"
    try:
        os.replace(active, displaced)
        os.replace(previous, active)
        launch_arguments(distribution, server_directory)
        manifest["used"] = True
        manifest["used_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
        _write_manifest(directory / "recovery.json", manifest)
    except (OSError, LaunchPlanError, UpgradeOperationError) as exc:
        try:
            if active.exists():
                active.unlink()
            if displaced.exists():
                os.replace(displaced, active)
        except OSError as rollback_exc:
            raise UpgradeOperationError(
                "Recovery failed and Blockstead could not restore the newer launch file. "
                "Leave the server stopped and inspect its recovery folder."
            ) from rollback_exc
        raise UpgradeOperationError(
            "The previous launch file could not be restored; the newer file remains active."
        ) from exc
    return manifest
