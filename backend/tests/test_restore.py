import hashlib
import io
import json
import os
import tarfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from blockstead.backups import (
    RestoreError,
    RetentionEntry,
    create_backup_archive,
    perform_restore,
    plan_restore,
    select_expired,
    verify_backup_archive,
)

NOW = datetime(2026, 7, 17, 14, 30, tzinfo=timezone.utc)  # noqa: UP017


def make_backup(server: Path, data: Path) -> tuple[str, str]:
    archive = create_backup_archive(
        "profile-1",
        server,
        data,
        "12345678-abcd",
        NOW,
        profile_name="Fixture",
        distribution="vanilla",
        minecraft_version="1.21.9",
        application_version="0.1.0",
        trigger="manual",
    )
    return archive.file_name, archive.manifest_name


def make_server(tmp_path: Path, worlds: dict[str, bytes]) -> Path:
    server = tmp_path / "server"
    for name, payload in worlds.items():
        (server / name).mkdir(parents=True)
        (server / name / "level.dat").write_bytes(payload)
    return server


def craft_hostile_backup(
    data: Path,
    members: list[tuple[tarfile.TarInfo, bytes | None]],
    included: list[str],
) -> tuple[str, str]:
    """Write an attacker-shaped archive with an internally consistent manifest."""

    folder = data / "backups" / "profile-1"
    folder.mkdir(parents=True, exist_ok=True)
    file_name = "20260717-140000-hostile1.tar.gz"
    manifest_name = "20260717-140000-hostile1.manifest.json"
    with tarfile.open(folder / file_name, "w:gz") as tar:
        for member, payload in members:
            tar.addfile(member, io.BytesIO(payload) if payload is not None else None)
    body = (folder / file_name).read_bytes()
    manifest = {
        "manifest_version": 1,
        "backup_id": "hostile",
        "profile_id": "profile-1",
        "profile_name": "Fixture",
        "distribution": "vanilla",
        "minecraft_version": None,
        "loader_version": None,
        "created_at": "2026-07-17T14:00:00+00:00",
        "method": "world_archive",
        "trigger": "manual",
        "included_paths": included,
        "excluded_links": 0,
        "archive": {
            "file_name": file_name,
            "size_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
        "application_version": "0.1.0",
    }
    (folder / manifest_name).write_text(json.dumps(manifest), encoding="utf-8")
    return file_name, manifest_name


def file_member(name: str, payload: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(payload)
    return member, payload


def test_plan_restore_verifies_and_reports_replacements(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)

    plan = plan_restore(data, "profile-1", file_name, manifest_name, server)

    assert plan.included_paths == ("world",)
    assert plan.worlds_replaced == ("world",)
    assert plan.size_bytes == (data / "backups" / "profile-1" / file_name).stat().st_size
    assert plan.available_bytes > 0
    assert plan.minecraft_version == "1.21.9"


def test_restore_replaces_worlds_and_preserves_originals(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original", "world_nether": b"nether"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    (server / "world" / "level.dat").write_bytes(b"changed after backup")
    (server / "world" / "new-chunk.mca").write_bytes(b"only in current world")

    result = perform_restore(data, "profile-1", file_name, manifest_name, server, NOW)

    assert result.restored_paths == ("world", "world_nether")
    assert (server / "world" / "level.dat").read_bytes() == b"original"
    assert not (server / "world" / "new-chunk.mca").exists()
    assert len(result.preserved_paths) == 2
    preserved_world = server / result.preserved_paths[0]
    assert preserved_world.name.startswith("world.pre-restore-")
    assert (preserved_world / "level.dat").read_bytes() == b"changed after backup"
    assert (preserved_world / "new-chunk.mca").exists()
    assert not (server / ".blockstead-restore.partial").exists()


def test_restore_rejects_tampered_archive(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    archive_path = data / "backups" / "profile-1" / file_name
    body = bytearray(archive_path.read_bytes())
    body[len(body) // 2] ^= 0xFF
    archive_path.write_bytes(bytes(body))

    with pytest.raises(RestoreError, match="checksum verification"):
        verify_backup_archive(data, "profile-1", file_name, manifest_name)


def test_restore_rejects_path_traversal_member(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = craft_hostile_backup(
        data, [file_member("world/../../evil.txt", b"escape")], ["world"]
    )

    with pytest.raises(RestoreError, match="unsafe file path"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)
    assert not (tmp_path / "evil.txt").exists()


def test_restore_rejects_absolute_member(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = craft_hostile_backup(
        data, [file_member("/world/evil.txt", b"escape")], ["world"]
    )

    with pytest.raises(RestoreError, match="unsafe file path"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_restore_rejects_link_members(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    link = tarfile.TarInfo("world/evil-link")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    file_name, manifest_name = craft_hostile_backup(data, [(link, None)], ["world"])

    with pytest.raises(RestoreError, match="links or special files"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_restore_rejects_parent_directory_manifest_roots(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = craft_hostile_backup(
        data, [file_member("../escape.txt", b"escape")], [".."]
    )

    with pytest.raises(RestoreError, match="unsupported format"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_restore_rejects_consistent_forgery_against_database_record(
    tmp_path: Path,
) -> None:
    """A rewritten archive-plus-manifest pair is internally consistent, so
    only the checksum Blockstead recorded at creation time can expose it."""

    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    folder = data / "backups" / "profile-1"
    recorded_sha = hashlib.sha256((folder / file_name).read_bytes()).hexdigest()

    (server / "world" / "level.dat").write_bytes(b"attacker world")
    forged_name, _ = craft_hostile_backup(
        data, [file_member("world/level.dat", b"attacker world")], ["world"]
    )
    (folder / file_name).write_bytes((folder / forged_name).read_bytes())
    forged_manifest = json.loads(
        (folder / "20260717-140000-hostile1.manifest.json").read_text(encoding="utf-8")
    )
    forged_manifest["archive"]["file_name"] = file_name
    (folder / manifest_name).write_text(json.dumps(forged_manifest), encoding="utf-8")

    plan_restore(data, "profile-1", file_name, manifest_name, server)
    with pytest.raises(RestoreError, match="does not match Blockstead's records"):
        plan_restore(
            data, "profile-1", file_name, manifest_name, server, expected_sha256=recorded_sha
        )


def test_restore_rejects_members_outside_recorded_worlds(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = craft_hostile_backup(
        data, [file_member("server.properties", b"tampered")], ["world"]
    )

    with pytest.raises(RestoreError, match="outside its recorded world folders"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_restore_requires_free_disk_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    usage = namedtuple("usage", "total used free")

    monkeypatch.setattr(
        "blockstead.backups.shutil.disk_usage", lambda _: usage(100, 100, 1024)
    )

    with pytest.raises(RestoreError, match="not enough free disk space"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_failed_swap_puts_original_worlds_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = make_server(tmp_path, {"world": b"original", "world_nether": b"nether"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    (server / "world" / "level.dat").write_bytes(b"current world")
    (server / "world_nether" / "level.dat").write_bytes(b"current nether")

    real_rename = os.rename

    def flaky_rename(src: str | Path, dst: str | Path) -> None:
        if ".blockstead-restore.partial" in str(src) and str(dst).endswith("world_nether"):
            raise OSError("simulated rename failure")
        real_rename(src, dst)

    monkeypatch.setattr("blockstead.backups.os.rename", flaky_rename)

    with pytest.raises(RestoreError, match="original worlds were kept"):
        perform_restore(data, "profile-1", file_name, manifest_name, server, NOW)

    assert (server / "world" / "level.dat").read_bytes() == b"current world"
    assert (server / "world_nether" / "level.dat").read_bytes() == b"current nether"
    assert not list(server.glob("*.pre-restore-*"))


def test_restore_survives_leftover_staging_directory(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    staging = server / ".blockstead-restore.partial"
    (staging / "world").mkdir(parents=True)
    (staging / "world" / "stale.dat").write_bytes(b"from an interrupted restore")

    result = perform_restore(data, "profile-1", file_name, manifest_name, server, NOW)

    assert result.restored_paths == ("world",)
    assert (server / "world" / "level.dat").read_bytes() == b"original"
    assert not (server / "world" / "stale.dat").exists()
    assert not staging.exists()


def entry(backup_id: str, days_old: int, size_mb: int) -> RetentionEntry:
    return RetentionEntry(
        backup_id=backup_id,
        created_at=NOW - timedelta(days=days_old),
        size_bytes=size_mb * 1024 * 1024,
    )


def test_retention_keeps_newest_regardless_of_rules() -> None:
    entries = [entry("only", 400, 100_000)]
    assert select_expired(entries, NOW, 1, 1, 1) == []


def test_retention_by_count_expires_oldest() -> None:
    entries = [entry("a", 3, 1), entry("b", 2, 1), entry("c", 1, 1)]
    assert select_expired(entries, NOW, 2, None, None) == ["a"]


def test_retention_by_age_expires_old_backups() -> None:
    entries = [entry("a", 40, 1), entry("b", 20, 1), entry("c", 1, 1)]
    assert select_expired(entries, NOW, None, 30, None) == ["a"]


def test_retention_by_total_size_expires_over_budget() -> None:
    entries = [entry("a", 3, 600), entry("b", 2, 600), entry("c", 1, 600)]
    assert select_expired(entries, NOW, None, None, 1300) == ["a"]


def test_retention_combines_rules() -> None:
    entries = [entry("a", 40, 600), entry("b", 20, 600), entry("c", 1, 600)]
    assert set(select_expired(entries, NOW, 2, 30, 700)) == {"a", "b"}


def test_restore_after_manual_archive_deletion_is_refused(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    file_name, manifest_name = make_backup(server, data)
    (data / "backups" / "profile-1" / file_name).unlink()

    with pytest.raises(RestoreError, match="no longer exists"):
        plan_restore(data, "profile-1", file_name, manifest_name, server)


def test_stored_names_cannot_traverse(tmp_path: Path) -> None:
    server = make_server(tmp_path, {"world": b"original"})
    data = tmp_path / "data"
    make_backup(server, data)

    with pytest.raises(RestoreError, match="not usable"):
        plan_restore(data, "profile-1", "../../../etc/passwd", "manifest.json", server)
