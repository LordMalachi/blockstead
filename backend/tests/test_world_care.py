from pathlib import Path

from blockstead.world_care import (
    CleanupTarget,
    check_backup_destination,
    remove_cleanup_targets,
)


def test_remove_cleanup_targets_removes_a_reviewed_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    drill = data_dir / "recovery-drills" / "stale-drill"
    drill.mkdir(parents=True)
    (drill / "level.dat").write_bytes(b"x")
    resolved = drill.resolve()
    target = CleanupTarget(
        relative_path="recovery-drills/stale-drill",
        kind="directory",
        size_bytes=1,
        modified_ns=resolved.stat().st_mtime_ns,
        label="Interrupted recovery drill staging",
        reason="stale",
        recovery_effect="not a backup",
    )

    removed = remove_cleanup_targets(data_dir, [target])

    assert removed == 1
    assert not drill.exists()


def test_check_backup_destination_leaves_directory_listable_by_owner(tmp_path: Path) -> None:
    """The write-verify-cleanup probe used to validate a mirror destination
    must leave the folder usable afterward, on every platform."""

    root = tmp_path / "mirrors"
    root.mkdir()
    destination = root / "chosen"

    result = check_backup_destination(destination, root)

    assert result["state"] == "available"
    assert result["write_verified"] is True
    assert result["read_verified"] is True
    # Still listable and writable by the owner after the check.
    list(destination.iterdir())
    probe = destination / "probe-after.txt"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def test_check_backup_destination_rejects_paths_outside_the_required_root(tmp_path: Path) -> None:
    root = tmp_path / "mirrors"
    root.mkdir()
    outside = tmp_path / "elsewhere"

    result = check_backup_destination(outside, root)

    assert result["write_verified"] is False
