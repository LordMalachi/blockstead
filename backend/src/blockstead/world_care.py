"""Storage evidence and guarded housekeeping helpers for World Care."""

import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


def tree_size(path: Path) -> int | None:
    """Return a regular-file tree size, or ``None`` when the view is incomplete."""

    if path.is_symlink() or not path.exists():
        return 0 if not path.exists() else None
    try:
        if path.is_file():
            return path.stat().st_size
        total = 0
        for entry in path.rglob("*"):
            if entry.is_symlink():
                continue
            if entry.is_file():
                total += entry.stat().st_size
        return total
    except OSError:
        return None


def disk_payload(path: Path) -> dict[str, object]:
    """Describe the filesystem containing ``path`` without calling a missing path healthy."""

    try:
        resolved = path.resolve()
        probe = resolved if resolved.exists() else resolved.parent
        usage = shutil.disk_usage(probe)
        return {
            "state": "available" if resolved.exists() and resolved.is_dir() else "missing",
            "path": str(resolved),
            "total_bytes": usage.total,
            "free_bytes": usage.free,
            "used_bytes": usage.used,
            "used_percent": usage.used / usage.total * 100 if usage.total else 0,
        }
    except OSError:
        return {
            "state": "unavailable",
            "path": str(path),
            "total_bytes": None,
            "free_bytes": None,
            "used_bytes": None,
            "used_percent": None,
        }


def recovery_snapshot_entries(
    server_directory: Path, data_directory: Path, profile_id: str
) -> list[dict[str, object]]:
    """List known recovery areas without exposing arbitrary files to the browser."""

    pre_restore = []
    if server_directory.is_dir():
        try:
            pre_restore = [
                child
                for child in server_directory.iterdir()
                if child.is_dir() and ".pre-restore" in child.name
            ]
        except OSError:
            pre_restore = []
    roots = [
        ("Pre-restore world copies", pre_restore),
        ("Server configuration backups", [server_directory / ".blockstead-config-backups"]),
        ("Settings snapshots", [data_directory / "settings-snapshots" / profile_id]),
        ("Extension recovery bundles", [data_directory / "extension-updates" / profile_id]),
        ("Server upgrade recovery", [data_directory / "server-upgrades" / profile_id]),
    ]
    entries: list[dict[str, object]] = []
    for label, paths in roots:
        size = 0
        present = False
        complete = True
        for path in paths:
            if not path.exists():
                continue
            present = True
            measured = tree_size(path)
            if measured is None:
                complete = False
            else:
                size += measured
        if present:
            entries.append(
                {
                    "label": label,
                    "size_bytes": size if complete else None,
                    "state": "available" if complete else "unknown",
                }
            )
    return entries


@dataclass(frozen=True)
class CleanupTarget:
    """A bounded, non-world artifact that can be reviewed before removal."""

    relative_path: str
    kind: str
    size_bytes: int | None
    modified_ns: int
    label: str
    reason: str
    recovery_effect: str


def _cleanup_target(data_directory: Path, path: Path, *, label: str, reason: str,
                    recovery_effect: str) -> CleanupTarget | None:
    """Describe a real regular file/directory below private data storage only."""

    try:
        root = data_directory.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if path.is_symlink() or resolved.is_symlink():
            return None
        size: int | None
        if resolved.is_file():
            kind = "file"
            size = resolved.stat().st_size
        elif resolved.is_dir():
            kind = "directory"
            size = tree_size(resolved)
        else:
            return None
        stat = resolved.stat()
    except (OSError, ValueError):
        return None
    return CleanupTarget(
        relative_path=resolved.relative_to(root).as_posix(),
        kind=kind,
        size_bytes=size,
        modified_ns=stat.st_mtime_ns,
        label=label,
        reason=reason,
        recovery_effect=recovery_effect,
    )


def _stored_name(path: Path, name: str | None) -> Path | None:
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        return None
    return path / name


def cleanup_candidates(
    data_directory: Path,
    profile_id: str,
    expired_backups: list[tuple[str | None, str | None]],
    now: datetime,
) -> list[CleanupTarget]:
    """Return only incomplete/expired private artifacts, never a live world.

    Recovery copies, completed backups, and active backup files are deliberately
    absent. Each candidate has an exact private-data path and is revalidated by
    ``remove_cleanup_targets`` before it can be removed.
    """

    targets: list[CleanupTarget] = []
    backup_root = data_directory / "backups" / profile_id
    partial_cutoff = now - timedelta(hours=1)
    try:
        partials = list(backup_root.iterdir()) if backup_root.is_dir() else []
    except OSError:
        partials = []
    for path in partials:
        try:
            stale = datetime.fromtimestamp(path.stat().st_mtime, UTC) < partial_cutoff
        except OSError:
            continue
        if (
            stale
            and path.is_file()
            and not path.is_symlink()
            and path.name.startswith(".")
            and path.name.endswith(".partial")
        ):
            target = _cleanup_target(
                data_directory,
                path,
                label="Interrupted backup fragment",
                reason="This temporary archive has not changed for at least one hour.",
                recovery_effect="It was never a completed, verified backup.",
            )
            if target is not None:
                targets.append(target)

    for file_name, manifest_name in expired_backups:
        for name, label in (
            (file_name, "Expired backup archive"),
            (manifest_name, "Expired backup manifest"),
        ):
            stored_path = _stored_name(backup_root, name)
            if stored_path is None:
                continue
            target = _cleanup_target(
                data_directory,
                stored_path,
                label=label,
                reason="This record is already expired by the retention policy.",
                recovery_effect="It is not an available recovery point.",
            )
            if target is not None:
                targets.append(target)

    drill_root = data_directory / "recovery-drills"
    drill_cutoff = now - timedelta(hours=1)
    try:
        drills = list(drill_root.iterdir()) if drill_root.is_dir() else []
    except OSError:
        drills = []
    expected_prefix = f"recovery-{profile_id[:8]}-"
    for path in drills:
        try:
            stale = datetime.fromtimestamp(path.stat().st_mtime, UTC) < drill_cutoff
        except OSError:
            continue
        if (
            stale
            and path.is_dir()
            and not path.is_symlink()
            and path.name.startswith(expected_prefix)
        ):
            target = _cleanup_target(
                data_directory,
                path,
                label="Interrupted recovery drill staging",
                reason="This private staging directory is older than one hour.",
                recovery_effect="Recovery drills use temporary copies only; this is not a backup.",
            )
            if target is not None:
                targets.append(target)

    capture_root = data_directory / "diagnostic-captures" / profile_id
    capture_cutoff = now - timedelta(days=30)
    try:
        captures = list(capture_root.iterdir()) if capture_root.is_dir() else []
    except OSError:
        captures = []
    for path in captures:
        try:
            stale = datetime.fromtimestamp(path.stat().st_mtime, UTC) < capture_cutoff
        except OSError:
            continue
        if stale and path.is_file() and not path.is_symlink() and path.suffix == ".txt":
            target = _cleanup_target(
                data_directory,
                path,
                label="Local diagnostic transcript",
                reason="This owner-exportable diagnostic transcript is older than 30 days.",
                recovery_effect="It is diagnostic evidence, not a world or recovery artifact.",
            )
            if target is not None:
                targets.append(target)
    return sorted(targets, key=lambda item: item.relative_path)


def remove_cleanup_targets(data_directory: Path, targets: list[CleanupTarget]) -> int:
    """Remove previously reviewed private artifacts after exact revalidation."""

    try:
        root = data_directory.resolve(strict=True)
    except OSError as exc:
        raise OSError("Blockstead's private data directory is unavailable.") from exc
    removed = 0
    for target in targets:
        requested = root / target.relative_path
        try:
            resolved = requested.resolve(strict=True)
            resolved.relative_to(root)
            if requested.is_symlink() or resolved.is_symlink():
                raise OSError("A reviewed cleanup target changed into a link.")
            current_kind = (
                "file" if resolved.is_file() else "directory" if resolved.is_dir() else None
            )
            current_size = (
                resolved.stat().st_size if current_kind == "file" else tree_size(resolved)
            )
            current_mtime = resolved.stat().st_mtime_ns
        except (OSError, ValueError) as exc:
            raise OSError("A reviewed cleanup target is no longer available.") from exc
        if (
            current_kind != target.kind
            or current_size != target.size_bytes
            or current_mtime != target.modified_ns
        ):
            raise OSError("A reviewed cleanup target changed after the plan was created.")
        if target.kind == "file":
            resolved.unlink()
        else:
            shutil.rmtree(resolved)
        removed += 1
    return removed


def check_backup_destination(target_directory: Path, required_root: Path) -> dict[str, object]:
    """Write, read, and remove a private nonce to verify one storage target."""

    try:
        root = required_root.resolve(strict=True)
        if not root.is_dir() or required_root.is_symlink():
            raise FileNotFoundError
    except FileNotFoundError:
        return {
            "state": "missing",
            "write_verified": False,
            "read_verified": False,
            "detail": "The configured destination folder is not available.",
        }
    except (OSError, ValueError):
        return {
            "state": "unavailable",
            "write_verified": False,
            "read_verified": False,
            "detail": "Blockstead could not access the configured destination folder.",
        }

    try:
        target_directory.relative_to(required_root)
        target_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_directory.resolve(strict=True)
        target.relative_to(root)
        if target.is_symlink() or not target.is_dir():
            raise OSError("The backup target is not a private folder.")
        nonce = secrets.token_bytes(32)
        probe = target / f".blockstead-storage-check-{secrets.token_hex(8)}"
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(nonce)
                handle.flush()
                os.fsync(handle.fileno())
            if probe.read_bytes() != nonce:
                raise OSError("The stored check token did not match.")
        finally:
            probe.unlink(missing_ok=True)
    except (OSError, ValueError):
        return {
            "state": "unavailable",
            "write_verified": False,
            "read_verified": False,
            "detail": "Blockstead could not complete a temporary write/read check here.",
        }
    return {
        "state": "available",
        "write_verified": True,
        "read_verified": True,
        "detail": "A private temporary file was written, read back, and removed.",
    }
