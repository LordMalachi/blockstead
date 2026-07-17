import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from blockstead.backups import BackupError, create_backup_archive


def test_backup_archives_world_directories_without_links(tmp_path: Path) -> None:
    server = tmp_path / "server"
    (server / "world" / "region").mkdir(parents=True)
    (server / "world_nether").mkdir()
    (server / "world" / "level.dat").write_bytes(b"world data")
    (server / "world_nether" / "level.dat").write_bytes(b"nether data")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not archive")
    (server / "world" / "linked-secret").symlink_to(secret)

    result = create_backup_archive(
        "profile-1",
        server,
        tmp_path / "data",
        "12345678-abcd",
        datetime(2026, 7, 17, 14, 30, tzinfo=timezone.utc),  # noqa: UP017
    )

    archive_path = tmp_path / "data" / "backups" / "profile-1" / result.file_name
    assert result.included_paths == ("world", "world_nether")
    assert archive_path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
    assert "world/level.dat" in names
    assert "world_nether/level.dat" in names
    assert "world/linked-secret" not in names


def test_backup_requires_a_world_directory(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()

    with pytest.raises(BackupError, match="No world directory"):
        create_backup_archive(
            "profile-1",
            server,
            tmp_path / "data",
            "12345678-abcd",
            datetime.now(timezone.utc),  # noqa: UP017
        )

    assert not (tmp_path / "data" / "backups").exists()
