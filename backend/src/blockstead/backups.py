"""Create, verify, and restore private, profile-scoped world archives."""

import hashlib
import json
import os
import re
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

MANIFEST_VERSION = 1
#: Extra free space demanded beyond the extracted size before a restore begins.
RESTORE_DISK_MARGIN_BYTES = 64 * 1024 * 1024
_STAGING_NAME = ".blockstead-restore.partial"
#: Standard-library extraction hardening where this Python provides it; our own
#: member validation in _validated_members remains the primary gate.
_DATA_FILTER = getattr(tarfile, "data_filter", None)


class BackupError(RuntimeError):
    """A backup could not be created; messages are safe to show to an owner."""


class RestoreError(RuntimeError):
    """A restore was refused or failed; messages are safe to show to an owner."""


@dataclass(frozen=True)
class BackupArchive:
    file_name: str
    manifest_name: str
    size_bytes: int
    sha256: str
    included_paths: tuple[str, ...]
    excluded_links: int


@dataclass(frozen=True)
class RestorePlan:
    file_name: str
    size_bytes: int
    sha256: str
    included_paths: tuple[str, ...]
    worlds_replaced: tuple[str, ...]
    required_bytes: int
    available_bytes: int
    created_at: str | None
    minecraft_version: str | None


@dataclass(frozen=True)
class RestoreResult:
    restored_paths: tuple[str, ...]
    preserved_paths: tuple[str, ...]


def backup_directory(destination_root: Path, profile_id: str) -> Path:
    return destination_root / "backups" / profile_id


def _stored_file(destination_root: Path, profile_id: str, file_name: str) -> Path:
    # File names come from Blockstead's own database, but never trust a stored
    # name enough to let it traverse out of the profile's backup folder.
    if not file_name or "/" in file_name or "\\" in file_name or file_name.startswith("."):
        raise RestoreError("This backup's archive name is not usable.")
    return backup_directory(destination_root, profile_id) / file_name


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


#: The safe shape Blockstead accepts for a configured world folder name; it
#: mirrors the guided editor's level-name rule and contains no glob or path
#: metacharacters.
_LEVEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_PROPERTIES_LIMIT = 1_000_000


def _configured_level_name(server_directory: Path) -> str | None:
    """The level-name from server.properties, when present and safely shaped."""

    path = server_directory / "server.properties"
    try:
        if not path.is_file() or path.stat().st_size > _PROPERTIES_LIMIT:
            return None
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "!")) or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == "level-name":
            value = value.strip()
            return value if _LEVEL_NAME.fullmatch(value) else None
    return None


def _world_roots(server_directory: Path) -> list[Path]:
    """World folders to protect: level-name based (Paper adds suffixed
    dimension folders) plus the vanilla ``world*`` convention."""

    prefixes = {"world"}
    level_name = _configured_level_name(server_directory)
    if level_name:
        prefixes.add(level_name)
    roots = {
        path
        for prefix in prefixes
        for path in server_directory.glob(f"{prefix}*")
        if path.is_dir() and not path.is_symlink()
    }
    return sorted(roots, key=lambda path: path.name)


def create_backup_archive(
    profile_id: str,
    server_directory: Path,
    destination_root: Path,
    backup_id: str,
    created_at: datetime,
    *,
    profile_name: str,
    distribution: str,
    minecraft_version: str | None,
    application_version: str,
    trigger: str,
) -> BackupArchive:
    roots = _world_roots(server_directory)
    if not roots:
        raise BackupError("No world directory was found for this server.")

    destination = backup_directory(destination_root, profile_id)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    file_name = f"{stamp}-{backup_id[:8]}.tar.gz"
    manifest_name = f"{stamp}-{backup_id[:8]}.manifest.json"
    archive_path = destination / file_name
    manifest_path = destination / manifest_name
    partial_path = destination / f".{file_name}.partial"
    manifest_partial = destination / f".{manifest_name}.partial"

    excluded_links = 0

    def keep_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # World folders can contain user-created links. Do not preserve links in
        # an archive that is eligible for automated restore.
        nonlocal excluded_links
        if member.issym() or member.islnk():
            excluded_links += 1
            return None
        return member

    try:
        with tarfile.open(partial_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for root in roots:
                archive.add(root, arcname=root.name, recursive=True, filter=keep_member)
        partial_path.chmod(0o600)
        sha256 = _sha256_of(partial_path)
        size_bytes = partial_path.stat().st_size
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "backup_id": backup_id,
            "profile_id": profile_id,
            "profile_name": profile_name,
            "distribution": distribution,
            "minecraft_version": minecraft_version,
            "loader_version": None,
            "created_at": created_at.astimezone(timezone.utc).isoformat(),  # noqa: UP017
            "method": "world_archive",
            "trigger": trigger,
            "included_paths": [root.name for root in roots],
            "excluded_links": excluded_links,
            "archive": {
                "file_name": file_name,
                "size_bytes": size_bytes,
                "sha256": sha256,
            },
            "application_version": application_version,
        }
        manifest_partial.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        manifest_partial.chmod(0o600)
        os.replace(partial_path, archive_path)
        try:
            os.replace(manifest_partial, manifest_path)
        except OSError:
            archive_path.unlink(missing_ok=True)
            raise
    except (OSError, tarfile.TarError) as exc:
        partial_path.unlink(missing_ok=True)
        manifest_partial.unlink(missing_ok=True)
        raise BackupError("The world archive could not be written.") from exc

    return BackupArchive(
        file_name=file_name,
        manifest_name=manifest_name,
        size_bytes=size_bytes,
        sha256=sha256,
        included_paths=tuple(root.name for root in roots),
        excluded_links=excluded_links,
    )


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RestoreError(
            "This backup has no manifest, so it cannot be verified for restore."
        ) from exc
    except (OSError, ValueError) as exc:
        raise RestoreError("This backup's manifest could not be read.") from exc
    if not isinstance(loaded, dict) or loaded.get("manifest_version") != MANIFEST_VERSION:
        raise RestoreError("This backup's manifest has an unsupported format.")
    return loaded


def verify_backup_archive(
    destination_root: Path,
    profile_id: str,
    file_name: str,
    manifest_name: str,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    """Confirm the archive matches its manifest; returns the manifest.

    ``expected_sha256`` is the checksum Blockstead recorded in its own
    database when the backup was created. Requiring it to match means a
    rewritten archive-plus-manifest pair in the backup folder still cannot
    pass verification.
    """

    archive_path = _stored_file(destination_root, profile_id, file_name)
    manifest_path = _stored_file(destination_root, profile_id, manifest_name)
    manifest = _load_manifest(manifest_path)
    described = manifest.get("archive")
    if (
        not isinstance(described, dict)
        or not isinstance(described.get("size_bytes"), int)
        or not isinstance(described.get("sha256"), str)
    ):
        raise RestoreError("This backup's manifest has an unsupported format.")
    if expected_sha256 is not None and described["sha256"] != expected_sha256:
        raise RestoreError(
            "This backup's manifest does not match Blockstead's records "
            "and will not be restored."
        )
    if not archive_path.is_file():
        raise RestoreError("This backup's archive file no longer exists.")
    size_bytes = archive_path.stat().st_size
    if described.get("file_name") != file_name or described.get("size_bytes") != size_bytes:
        raise RestoreError("This backup's archive does not match its manifest.")
    if _sha256_of(archive_path) != described["sha256"]:
        raise RestoreError(
            "This backup failed checksum verification and will not be restored. "
            "The archive may be damaged."
        )
    return manifest


def _validated_members(
    archive: tarfile.TarFile, allowed_roots: frozenset[str]
) -> list[tarfile.TarInfo]:
    members = []
    for member in archive:
        name = PurePosixPath(member.name)
        if name.is_absolute() or any(part in {"..", ""} for part in name.parts):
            raise RestoreError("This backup contains an unsafe file path and will not be restored.")
        if not member.isfile() and not member.isdir():
            raise RestoreError(
                "This backup contains links or special files and will not be restored."
            )
        if name.parts[0] not in allowed_roots:
            raise RestoreError(
                "This backup contains files outside its recorded world folders "
                "and will not be restored."
            )
        members.append(member)
    if not members:
        raise RestoreError("This backup's archive is empty.")
    return members


def _manifest_roots(manifest: dict[str, object]) -> tuple[str, ...]:
    included = manifest.get("included_paths")
    if (
        not isinstance(included, list)
        or not included
        or not all(
            isinstance(item, str)
            # A tampered manifest must not be able to point the world swap at
            # a parent, hidden, or nested path.
            and item
            and not item.startswith(".")
            and "/" not in item
            and "\\" not in item
            for item in included
        )
    ):
        raise RestoreError("This backup's manifest has an unsupported format.")
    return tuple(included)


def plan_restore(
    destination_root: Path,
    profile_id: str,
    file_name: str,
    manifest_name: str,
    server_directory: Path,
    expected_sha256: str | None = None,
) -> RestorePlan:
    manifest = verify_backup_archive(
        destination_root, profile_id, file_name, manifest_name, expected_sha256
    )
    roots = _manifest_roots(manifest)
    archive_path = _stored_file(destination_root, profile_id, file_name)
    total_bytes = 0
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in _validated_members(archive, frozenset(roots)):
                total_bytes += max(member.size, 0)
    except tarfile.TarError as exc:
        raise RestoreError("This backup's archive could not be read.") from exc

    worlds_replaced = tuple(
        name for name in roots if (server_directory / name).exists()
    )
    required = total_bytes + RESTORE_DISK_MARGIN_BYTES
    available = shutil.disk_usage(server_directory).free
    if available < required:
        raise RestoreError(
            "There is not enough free disk space to restore this backup safely. "
            f"About {required // (1024 * 1024)} MB is needed."
        )
    described = manifest["archive"]
    assert isinstance(described, dict)
    described_size = described["size_bytes"]
    described_sha = described["sha256"]
    assert isinstance(described_size, int) and isinstance(described_sha, str)
    created_at = manifest.get("created_at")
    minecraft_version = manifest.get("minecraft_version")
    return RestorePlan(
        file_name=file_name,
        size_bytes=described_size,
        sha256=described_sha,
        included_paths=roots,
        worlds_replaced=worlds_replaced,
        required_bytes=required,
        available_bytes=available,
        created_at=created_at if isinstance(created_at, str) else None,
        minecraft_version=minecraft_version if isinstance(minecraft_version, str) else None,
    )


def perform_restore(
    destination_root: Path,
    profile_id: str,
    file_name: str,
    manifest_name: str,
    server_directory: Path,
    now: datetime,
    expected_sha256: str | None = None,
) -> RestoreResult:
    """Extract to staging, validate, then swap worlds while preserving originals."""

    plan = plan_restore(
        destination_root,
        profile_id,
        file_name,
        manifest_name,
        server_directory,
        expected_sha256,
    )
    archive_path = _stored_file(destination_root, profile_id, file_name)
    staging = server_directory / _STAGING_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(mode=0o700)

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            if _DATA_FILTER is not None:
                archive.extraction_filter = _DATA_FILTER
            for member in _validated_members(archive, frozenset(plan.included_paths)):
                # Attributes are deliberately not preserved: extracted files get
                # fresh service-account ownership and umask permissions.
                archive.extract(member, path=staging, set_attrs=False)
    except (OSError, tarfile.TarError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RestoreError("The backup could not be unpacked for restore.") from exc

    present = [name for name in plan.included_paths if (staging / name).is_dir()]
    if tuple(present) != plan.included_paths:
        shutil.rmtree(staging, ignore_errors=True)
        raise RestoreError("The unpacked backup is missing an expected world folder.")

    stamp = now.strftime("pre-restore-%Y%m%d-%H%M%S")
    preserved: list[str] = []
    swapped: list[str] = []
    try:
        for name in plan.included_paths:
            target = server_directory / name
            keep_name = f"{name}.{stamp}"
            moved_away = False
            if target.exists():
                os.rename(target, server_directory / keep_name)
                moved_away = True
            try:
                os.rename(staging / name, target)
            except OSError:
                # Put this world's original straight back before unwinding.
                if moved_away:
                    os.rename(server_directory / keep_name, target)
                raise
            if moved_away:
                preserved.append(keep_name)
            swapped.append(name)
    except OSError as exc:
        # Walk the completed swaps back so the server keeps its original worlds.
        for name in reversed(swapped):
            restored_target = server_directory / name
            try:
                os.rename(restored_target, staging / name)
            except OSError:
                continue
            keep_name = f"{name}.{stamp}"
            if (server_directory / keep_name).exists():
                try:
                    os.rename(server_directory / keep_name, restored_target)
                except OSError:
                    pass
        raise RestoreError(
            "The restore could not replace the world folders. "
            "The original worlds were kept, some possibly under their "
            f"{stamp} names."
        ) from exc

    shutil.rmtree(staging, ignore_errors=True)
    return RestoreResult(restored_paths=tuple(swapped), preserved_paths=tuple(preserved))


@dataclass(frozen=True)
class RetentionEntry:
    backup_id: str
    created_at: datetime
    size_bytes: int


def select_expired(
    entries: list[RetentionEntry],
    now: datetime,
    keep_count: int | None,
    keep_days: int | None,
    max_total_mb: int | None,
) -> list[str]:
    """Choose completed backups that retention should remove.

    ``entries`` must contain only completed backups whose archives still exist.
    The newest entry is never selected: the only known-good backup survives
    every policy.
    """

    ordered = sorted(entries, key=lambda entry: entry.created_at, reverse=True)
    if len(ordered) <= 1:
        return []
    expired: dict[str, bool] = {}
    if keep_count is not None:
        for entry in ordered[max(keep_count, 1):]:
            expired[entry.backup_id] = True
    if keep_days is not None:
        cutoff = now - timedelta(days=keep_days)
        for entry in ordered[1:]:
            if entry.created_at < cutoff:
                expired[entry.backup_id] = True
    if max_total_mb is not None:
        budget = max_total_mb * 1024 * 1024
        used = ordered[0].size_bytes
        for entry in ordered[1:]:
            used += entry.size_bytes
            if used > budget:
                expired[entry.backup_id] = True
    return [entry.backup_id for entry in ordered if entry.backup_id in expired]
