"""Reviewed extension updates and persistent, per-change rollback bundles."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .catalog import PlannedFile
from .extension_ops import ExtensionOpsError, ensure_managed_directory
from .modrinth import JAR_NAME_PATTERN

RECOVERY_ID_LENGTH = 24


class ExtensionUpdateFile(BaseModel):
    file_name: str
    version_number: str | None
    role: Literal["replacement", "dependency"]
    action: Literal["replace", "install", "already_present"]
    required_by: str | None = None


class ExtensionUpdateReview(BaseModel):
    review_id: str
    file_name: str
    installed_version: str | None
    new_file_name: str
    new_version_number: str | None
    project_id: str
    version_id: str
    minecraft_version: str | None
    distribution: str
    required_java_major: int | None
    files: list[ExtensionUpdateFile] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    restart_required: bool = True
    rollback_detail: str


class ExtensionRecoveryError(RuntimeError):
    """An extension recovery operation failed; messages are safe to show."""


def review_id(
    *,
    profile_id: str,
    installed_name: str,
    installed_sha512: str,
    planned: list[PlannedFile],
) -> str:
    parts = [profile_id, installed_name, installed_sha512]
    parts.extend(
        "\x1e".join(
            (
                item.project_id,
                item.version_id,
                item.version_number or "",
                item.file_name,
                item.checksum_algorithm or "",
                item.checksum or "",
                item.required_by or "",
            )
        )
        for item in planned
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def build_review(
    *,
    profile_id: str,
    distribution: str,
    minecraft_version: str | None,
    required_java: int | None,
    installed_name: str,
    installed_version: str | None,
    installed_sha512: str,
    planned: list[PlannedFile],
    existing_names: frozenset[str],
) -> ExtensionUpdateReview:
    if not planned:
        raise ExtensionRecoveryError("The update plan did not contain a replacement file.")
    root = planned[0]
    files: list[ExtensionUpdateFile] = []
    for index, item in enumerate(planned):
        role: Literal["replacement", "dependency"] = (
            "replacement" if index == 0 else "dependency"
        )
        if role == "replacement":
            action: Literal["replace", "install", "already_present"] = "replace"
        elif item.file_name in existing_names:
            action = "already_present"
        else:
            action = "install"
        files.append(
            ExtensionUpdateFile(
                file_name=item.file_name,
                version_number=item.version_number,
                role=role,
                action=action,
                required_by=item.required_by,
            )
        )
    return ExtensionUpdateReview(
        review_id=review_id(
            profile_id=profile_id,
            installed_name=installed_name,
            installed_sha512=installed_sha512,
            planned=planned,
        ),
        file_name=installed_name,
        installed_version=installed_version,
        new_file_name=root.file_name,
        new_version_number=root.version_number,
        project_id=root.project_id,
        version_id=root.version_id,
        minecraft_version=minecraft_version,
        distribution=distribution,
        required_java_major=required_java,
        files=files,
        dependencies=[
            item.file_name
            for item in files
            if item.role == "dependency" and item.action != "already_present"
        ],
        rollback_detail=(
            "Blockstead keeps the exact replaced jar in a private recovery bundle. "
            "Undo is offered only while the newly installed files still match this "
            "review, and it never changes world data."
        ),
    )


def _manifest_path(directory: Path) -> Path:
    return directory / "recovery.json"


def _write_manifest(directory: Path, payload: dict[str, object]) -> None:
    path = _manifest_path(directory)
    temporary = directory / ".recovery.json.partial"
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ExtensionRecoveryError(
            "Blockstead could not record the extension recovery instructions."
        ) from exc


def prepare_recovery(
    *,
    recovery_root: Path,
    profile_id: str,
    extension_directory: Path,
    review: ExtensionUpdateReview,
    installed_sha512: str,
) -> tuple[str, Path]:
    directory = ensure_managed_directory(extension_directory)
    source = directory / review.file_name
    if source.is_symlink() or not source.is_file():
        raise ExtensionRecoveryError("The extension selected for update is no longer available.")
    recovery_id = secrets.token_hex(RECOVERY_ID_LENGTH // 2)
    recovery = recovery_root / "extension-updates" / profile_id / recovery_id
    try:
        recovery.mkdir(parents=True, mode=0o700)
        recovery.chmod(0o700)
        shutil.copy2(source, recovery / review.file_name)
        (recovery / review.file_name).chmod(0o600)
        _write_manifest(
            recovery,
            {
                "schema": 1,
                "profile_id": profile_id,
                "review_id": review.review_id,
                "old_file": review.file_name,
                "old_sha512": installed_sha512,
                "new_files": [],
                "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                "ready": False,
                "used": False,
            },
        )
    except (OSError, ExtensionOpsError, ExtensionRecoveryError):
        shutil.rmtree(recovery, ignore_errors=True)
        raise
    return recovery_id, recovery


def finalize_recovery(
    recovery: Path,
    *,
    new_files: list[tuple[str, str, str]],
) -> None:
    try:
        payload = json.loads(_manifest_path(recovery).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExtensionRecoveryError(
            "The extension changed, but its recovery record could not be completed."
        ) from exc
    if not isinstance(payload, dict):
        raise ExtensionRecoveryError(
            "The extension changed, but its recovery record is not usable."
        )
    payload["new_files"] = [
        {"file_name": file_name, "checksum_algorithm": algorithm, "checksum": checksum}
        for file_name, algorithm, checksum in new_files
    ]
    payload["ready"] = True
    _write_manifest(recovery, payload)


def discard_recovery(recovery: Path) -> None:
    shutil.rmtree(recovery, ignore_errors=True)


def _read_recovery(
    recovery_root: Path, profile_id: str, recovery_id: str
) -> tuple[Path, dict[str, object]]:
    if (
        len(recovery_id) != RECOVERY_ID_LENGTH
        or not all(character in "0123456789abcdef" for character in recovery_id)
    ):
        raise ExtensionRecoveryError("That extension recovery id is not valid.")
    directory = recovery_root / "extension-updates" / profile_id / recovery_id
    try:
        payload = json.loads(_manifest_path(directory).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExtensionRecoveryError("That extension recovery record could not be read.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("profile_id") != profile_id
        or payload.get("ready") is not True
    ):
        raise ExtensionRecoveryError("That extension recovery record is not usable.")
    return directory, payload


def rollback_update(
    *,
    recovery_root: Path,
    profile_id: str,
    recovery_id: str,
    extension_directory: Path,
) -> dict[str, object]:
    recovery, payload = _read_recovery(recovery_root, profile_id, recovery_id)
    if payload.get("used") is True:
        raise ExtensionRecoveryError("That extension recovery has already been used.")
    old_name = payload.get("old_file")
    old_sha512 = payload.get("old_sha512")
    new_files = payload.get("new_files")
    if (
        not isinstance(old_name, str)
        or not JAR_NAME_PATTERN.match(old_name)
        or not isinstance(old_sha512, str)
        or not isinstance(new_files, list)
    ):
        raise ExtensionRecoveryError("That extension recovery record is incomplete.")

    directory = ensure_managed_directory(extension_directory)
    old = recovery / old_name
    if old.is_symlink() or not old.is_file():
        raise ExtensionRecoveryError("The preserved extension file is no longer available.")
    sha512 = hashlib.sha512(old.read_bytes()).hexdigest()
    if sha512 != old_sha512:
        raise ExtensionRecoveryError(
            "The preserved extension file failed verification and will not be restored."
        )

    verified_new: list[Path] = []
    for item in new_files:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("file_name"), str)
            or not JAR_NAME_PATTERN.match(item["file_name"])
            or item.get("checksum_algorithm") not in {"sha1", "sha256", "sha512"}
            or not isinstance(item.get("checksum"), str)
        ):
            raise ExtensionRecoveryError("That extension recovery record is incomplete.")
        target = directory / item["file_name"]
        algorithm = str(item["checksum_algorithm"])
        digest = hashlib.new(algorithm)
        if target.is_symlink() or not target.is_file():
            raise ExtensionRecoveryError(
                "An installed extension file changed after the update, so Blockstead "
                "will not overwrite this loadout with an older recovery bundle."
            )
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().casefold() != str(item["checksum"]).casefold():
            raise ExtensionRecoveryError(
                "An installed extension file changed after the update, so Blockstead "
                "will not overwrite this loadout with an older recovery bundle."
            )
        verified_new.append(target)

    displaced = recovery / ".displaced"
    moved: list[Path] = []
    try:
        displaced.mkdir(mode=0o700)
        for target in verified_new:
            os.replace(target, displaced / target.name)
            moved.append(target)
        if (directory / old_name).exists() or (directory / old_name).is_symlink():
            raise ExtensionRecoveryError(
                f"A file named {old_name} now exists, so the older copy was not restored."
            )
        os.replace(old, directory / old_name)
        payload["used"] = True
        payload["used_at"] = datetime.now(timezone.utc).isoformat()  # noqa: UP017
        _write_manifest(recovery, payload)
    except (OSError, ExtensionRecoveryError) as exc:
        try:
            restored_old = directory / old_name
            if restored_old.exists() and not old.exists():
                os.replace(restored_old, old)
            for target in reversed(moved):
                os.replace(displaced / target.name, target)
        except OSError as rollback_exc:
            raise ExtensionRecoveryError(
                "Extension recovery failed and Blockstead could not fully restore the "
                "newer loadout. Leave the server stopped and inspect its recovery folder."
            ) from rollback_exc
        if isinstance(exc, ExtensionRecoveryError):
            raise
        raise ExtensionRecoveryError(
            "The older extension could not be restored; the newer loadout remains active."
        ) from exc
    return payload
