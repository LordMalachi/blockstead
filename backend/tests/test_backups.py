import hashlib
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from blockstead.backups import BackupError, create_backup_archive


def make_archive(server: Path, data: Path, backup_id: str = "12345678-abcd"):  # noqa: ANN201
    return create_backup_archive(
        "profile-1",
        server,
        data,
        backup_id,
        datetime(2026, 7, 17, 14, 30, tzinfo=timezone.utc),  # noqa: UP017
        profile_name="Fixture",
        distribution="vanilla",
        minecraft_version="1.21.9",
        application_version="0.1.0",
        trigger="manual",
    )


def test_backup_archives_world_directories_without_links(tmp_path: Path) -> None:
    server = tmp_path / "server"
    (server / "world" / "region").mkdir(parents=True)
    (server / "world_nether").mkdir()
    (server / "world" / "level.dat").write_bytes(b"world data")
    (server / "world_nether" / "level.dat").write_bytes(b"nether data")
    secret = tmp_path / "secret.txt"
    secret.write_text("do not archive")
    (server / "world" / "linked-secret").symlink_to(secret)

    result = make_archive(server, tmp_path / "data")

    archive_path = tmp_path / "data" / "backups" / "profile-1" / result.file_name
    assert result.included_paths == ("world", "world_nether")
    assert result.excluded_links == 1
    assert archive_path.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
    assert "world/level.dat" in names
    assert "world_nether/level.dat" in names
    assert "world/linked-secret" not in names


def test_backup_writes_matching_manifest(tmp_path: Path) -> None:
    server = tmp_path / "server"
    (server / "world").mkdir(parents=True)
    (server / "world" / "level.dat").write_bytes(b"world data")

    result = make_archive(server, tmp_path / "data")

    folder = tmp_path / "data" / "backups" / "profile-1"
    manifest_path = folder / result.manifest_name
    assert manifest_path.stat().st_mode & 0o777 == 0o600
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["profile_id"] == "profile-1"
    assert manifest["profile_name"] == "Fixture"
    assert manifest["distribution"] == "vanilla"
    assert manifest["minecraft_version"] == "1.21.9"
    assert manifest["application_version"] == "0.1.0"
    assert manifest["trigger"] == "manual"
    assert manifest["included_paths"] == ["world"]
    assert manifest["archive"]["file_name"] == result.file_name
    archive_bytes = (folder / result.file_name).read_bytes()
    assert manifest["archive"]["size_bytes"] == len(archive_bytes)
    assert manifest["archive"]["sha256"] == hashlib.sha256(archive_bytes).hexdigest()
    assert result.sha256 == manifest["archive"]["sha256"]


def test_backup_requires_a_world_directory(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()

    with pytest.raises(BackupError, match="No world directory"):
        make_archive(server, tmp_path / "data")

    assert not (tmp_path / "data" / "backups").exists()
