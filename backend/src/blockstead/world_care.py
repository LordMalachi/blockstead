"""Read-only storage evidence used by the World Care workspace."""

import shutil
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
