"""Create private, profile-scoped world archives."""

import os
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class BackupError(RuntimeError):
    """A backup could not be created; messages are safe to show to an owner."""


@dataclass(frozen=True)
class BackupArchive:
    file_name: str
    size_bytes: int
    included_paths: tuple[str, ...]


def _archive_member(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    # World folders can contain user-created links. Do not preserve links in an
    # archive that will eventually be eligible for automated restore.
    return None if member.issym() or member.islnk() else member


def create_backup_archive(
    profile_id: str,
    server_directory: Path,
    destination_root: Path,
    backup_id: str,
    created_at: datetime,
) -> BackupArchive:
    roots = sorted(
        (
            path
            for path in server_directory.glob("world*")
            if path.is_dir() and not path.is_symlink()
        ),
        key=lambda path: path.name,
    )
    if not roots:
        raise BackupError("No world directory was found for this server.")

    destination = destination_root / "backups" / profile_id
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    file_name = f"{stamp}-{backup_id[:8]}.tar.gz"
    archive_path = destination / file_name
    partial_path = destination / f".{file_name}.partial"

    try:
        with tarfile.open(partial_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            for root in roots:
                archive.add(root, arcname=root.name, recursive=True, filter=_archive_member)
        partial_path.chmod(0o600)
        os.replace(partial_path, archive_path)
    except (OSError, tarfile.TarError) as exc:
        partial_path.unlink(missing_ok=True)
        raise BackupError("The world archive could not be written.") from exc

    return BackupArchive(
        file_name=file_name,
        size_bytes=archive_path.stat().st_size,
        included_paths=tuple(root.name for root in roots),
    )
