import errno
import hashlib
from pathlib import Path

import pytest

import blockstead.upgrade_ops as upgrade_ops
from blockstead.upgrade_ops import (
    UpgradeOperationError,
    active_launch_file,
    create_upgrade_staging,
    list_available_launch_recoveries,
    promote_launch_upgrade,
    restore_newer_launch_after_failed_recovery,
    rollback_launch_upgrade,
)


def test_direct_upgrade_preserves_and_can_restore_the_launch_file(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.jar").write_bytes(b"old server")
    staging = create_upgrade_staging(server)
    (staging / "server.jar").write_bytes(b"new server")

    recovery = promote_launch_upgrade(
        server_directory=server,
        distribution="vanilla",
        staged_file=staging / "server.jar",
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        previous_version="1.21.4",
        new_version="1.21.6",
        previous_loader_version=None,
        new_loader_version=None,
    )

    assert active_launch_file("vanilla", server).read_bytes() == b"new server"
    assert (recovery.recovery_directory / "server.jar").read_bytes() == b"old server"
    available = list_available_launch_recoveries(
        server_directory=server,
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        distribution="vanilla",
    )
    assert [item["recovery_id"] for item in available] == [recovery.recovery_id]

    manifest = rollback_launch_upgrade(
        server_directory=server,
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        recovery_id=recovery.recovery_id,
        distribution="vanilla",
    )
    assert (server / "server.jar").read_bytes() == b"old server"
    assert manifest["previous_version"] == "1.21.4"
    assert manifest["used"] is True
    assert list_available_launch_recoveries(
        server_directory=server,
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        distribution="vanilla",
    ) == []

    restore_newer_launch_after_failed_recovery(
        server_directory=server,
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        recovery_id=recovery.recovery_id,
        distribution="vanilla",
    )
    assert (server / "server.jar").read_bytes() == b"new server"
    assert [
        item["recovery_id"]
        for item in list_available_launch_recoveries(
            server_directory=server,
            recovery_root=tmp_path / "data",
            profile_id="profile-1",
            distribution="vanilla",
        )
    ] == [recovery.recovery_id]


def test_recovery_refuses_to_overwrite_a_launch_file_changed_after_upgrade(
    tmp_path: Path,
) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.jar").write_bytes(b"old")
    staging = create_upgrade_staging(server)
    (staging / "server.jar").write_bytes(b"new")
    recovery = promote_launch_upgrade(
        server_directory=server,
        distribution="vanilla",
        staged_file=staging / "server.jar",
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        previous_version="1.0",
        new_version="2.0",
        previous_loader_version=None,
        new_loader_version=None,
    )
    (server / "server.jar").write_bytes(b"owner changed this")

    with pytest.raises(UpgradeOperationError, match="changed after this upgrade"):
        rollback_launch_upgrade(
            server_directory=server,
            recovery_root=tmp_path / "data",
            profile_id="profile-1",
            recovery_id=recovery.recovery_id,
            distribution="vanilla",
        )

    assert hashlib.sha256((server / "server.jar").read_bytes()).hexdigest() == hashlib.sha256(
        b"owner changed this"
    ).hexdigest()


def _upgrade_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.jar").write_bytes(b"old server")
    staging = create_upgrade_staging(server)
    (staging / "server.jar").write_bytes(b"new server")
    return server, staging, tmp_path / "data"


def _promote_inputs(
    server: Path, staging: Path, recovery_root: Path
) -> dict[str, object]:
    return {
        "server_directory": server,
        "distribution": "vanilla",
        "staged_file": staging / "server.jar",
        "recovery_root": recovery_root,
        "profile_id": "profile-1",
        "previous_version": "1.0",
        "new_version": "2.0",
        "previous_loader_version": None,
        "new_loader_version": None,
    }


def test_cross_filesystem_roots_are_copied_before_same_filesystem_renames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    real_replace = upgrade_ops.os.replace
    cross_root_attempts: list[tuple[Path, Path]] = []

    def under(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

    def reject_cross_root(source: Path, destination: Path) -> None:
        if (
            under(source, server)
            and under(destination, recovery_root)
            or under(source, recovery_root)
            and under(destination, server)
        ):
            cross_root_attempts.append((source, destination))
            raise OSError(errno.EXDEV, "injected cross-filesystem rename")
        real_replace(source, destination)

    monkeypatch.setattr(upgrade_ops.os, "replace", reject_cross_root)

    recovery = promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))
    assert (server / "server.jar").read_bytes() == b"new server"
    manifest = rollback_launch_upgrade(
        server_directory=server,
        recovery_root=recovery_root,
        profile_id="profile-1",
        recovery_id=recovery.recovery_id,
        distribution="vanilla",
    )

    assert (server / "server.jar").read_bytes() == b"old server"
    assert (recovery.recovery_directory / "replaced-server.jar").read_bytes() == b"new server"
    assert manifest["used"] is True
    assert cross_root_attempts == []


def test_recovery_copy_write_failure_leaves_active_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)

    def fail_fsync(descriptor: int) -> None:
        raise OSError(errno.EIO, "injected copy flush failure")

    monkeypatch.setattr(upgrade_ops.os, "fsync", fail_fsync)

    with pytest.raises(UpgradeOperationError, match="could not create and flush"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    assert (server / "server.jar").read_bytes() == b"old server"


def test_recovery_copy_staging_failure_leaves_active_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)

    def fail_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        raise OSError(errno.ENOSPC, "injected recovery staging failure")

    monkeypatch.setattr(upgrade_ops.tempfile, "mkstemp", fail_mkstemp)

    with pytest.raises(UpgradeOperationError, match="could not create and flush"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    assert (server / "server.jar").read_bytes() == b"old server"


def test_recovery_copy_fsync_failure_leaves_active_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)

    def fail_fsync_path(path: Path) -> None:
        raise OSError(errno.ENOSPC, "injected durable flush failure")

    monkeypatch.setattr(upgrade_ops, "fsync_path", fail_fsync_path)

    with pytest.raises(UpgradeOperationError, match="could not create and flush"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    assert (server / "server.jar").read_bytes() == b"old server"


def test_recovery_copy_hash_failure_leaves_active_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    real_sha256 = upgrade_ops._sha256

    def fail_recovery_hash(path: Path) -> str:
        if recovery_root == path or recovery_root in path.parents:
            return "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(upgrade_ops, "_sha256", fail_recovery_hash)

    with pytest.raises(UpgradeOperationError, match="could not verify the copied"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    assert (server / "server.jar").read_bytes() == b"old server"


def test_promotion_failure_restores_the_prior_launch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    real_replace = upgrade_ops.os.replace

    def fail_promoting(source: Path, destination: Path) -> None:
        if source == staging / "server.jar" and destination == server / "server.jar":
            raise OSError("injected promotion failure")
        real_replace(source, destination)

    monkeypatch.setattr(upgrade_ops.os, "replace", fail_promoting)

    with pytest.raises(UpgradeOperationError, match="prior launch file was restored"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    assert (server / "server.jar").read_bytes() == b"old server"


def test_promotion_restore_failure_keeps_recovery_copy_and_reports_its_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    real_replace = upgrade_ops.os.replace

    def fail_restoring(source: Path, destination: Path) -> None:
        is_server_displaced = (
            source.parent == server
            and source.name.startswith(".blockstead-r-")
            and source.name.endswith("-d")
        )
        if is_server_displaced and destination == server / "server.jar":
            raise OSError("injected restore failure")
        real_replace(source, destination)

    monkeypatch.setattr(upgrade_ops.os, "replace", fail_restoring)
    monkeypatch.setattr(
        upgrade_ops,
        "_write_manifest",
        lambda path, payload: (_ for _ in ()).throw(
            UpgradeOperationError("injected manifest failure")
        ),
    )

    with pytest.raises(UpgradeOperationError) as raised:
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    recovery_directory = next((recovery_root / "server-upgrades" / "profile-1").iterdir())
    assert (recovery_directory / "server.jar").read_bytes() == b"old server"
    assert (server / "server.jar").read_bytes() == b"new server"
    server_displaced = next(server.glob(".blockstead-r-*-d"))
    assert server_displaced.read_bytes() == b"old server"
    assert str(recovery_directory) in str(raised.value)


def test_transient_manifest_failure_can_be_retried_without_losing_the_prior_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    real_write_manifest = upgrade_ops._write_manifest
    failed = False

    def fail_once(path: Path, payload: dict[str, object]) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise UpgradeOperationError("injected manifest failure")
        real_write_manifest(path, payload)

    monkeypatch.setattr(upgrade_ops, "_write_manifest", fail_once)

    with pytest.raises(UpgradeOperationError, match="prior launch file was restored"):
        promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))
    assert (server / "server.jar").read_bytes() == b"old server"

    retry_staging = create_upgrade_staging(server)
    (retry_staging / "server.jar").write_bytes(b"new server retry")
    retry_inputs = _promote_inputs(server, retry_staging, recovery_root)
    recovery = promote_launch_upgrade(**retry_inputs)

    assert (server / "server.jar").read_bytes() == b"new server retry"
    assert (recovery.recovery_directory / "server.jar").read_bytes() == b"old server"


def test_recovery_initial_move_failure_keeps_both_launch_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    recovery = promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))

    def fail_initial_move(source: Path, destination: Path) -> None:
        raise OSError("injected initial recovery failure")

    monkeypatch.setattr(upgrade_ops.os, "replace", fail_initial_move)

    with pytest.raises(UpgradeOperationError):
        rollback_launch_upgrade(
            server_directory=server,
            recovery_root=recovery_root,
            profile_id="profile-1",
            recovery_id=recovery.recovery_id,
            distribution="vanilla",
        )

    assert (server / "server.jar").read_bytes() == b"new server"
    assert (recovery.recovery_directory / "server.jar").read_bytes() == b"old server"


def test_recovery_manifest_failure_restores_new_and_preserves_old_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    recovery = promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))
    real_write_manifest = upgrade_ops._write_manifest
    monkeypatch.setattr(
        upgrade_ops,
        "_write_manifest",
        lambda path, payload: (_ for _ in ()).throw(
            UpgradeOperationError("injected manifest failure")
        ),
    )

    with pytest.raises(UpgradeOperationError, match="newer file remains active"):
        rollback_launch_upgrade(
            server_directory=server,
            recovery_root=recovery_root,
            profile_id="profile-1",
            recovery_id=recovery.recovery_id,
            distribution="vanilla",
        )

    assert (server / "server.jar").read_bytes() == b"new server"
    assert (recovery.recovery_directory / "server.jar").read_bytes() == b"old server"

    monkeypatch.setattr(upgrade_ops, "_write_manifest", real_write_manifest)
    recovered = rollback_launch_upgrade(
        server_directory=server,
        recovery_root=recovery_root,
        profile_id="profile-1",
        recovery_id=recovery.recovery_id,
        distribution="vanilla",
    )
    assert (server / "server.jar").read_bytes() == b"old server"
    assert recovered["used"] is True


def test_recovery_compensation_failure_keeps_old_active_and_new_displaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, staging, recovery_root = _upgrade_inputs(tmp_path)
    recovery = promote_launch_upgrade(**_promote_inputs(server, staging, recovery_root))
    real_replace = upgrade_ops.os.replace

    def fail_preserving_old(source: Path, destination: Path) -> None:
        is_server_displaced = (
            source.parent == server
            and source.name.startswith(".blockstead-r-")
            and source.name.endswith("-d")
        )
        if is_server_displaced and destination == server / "server.jar":
            raise OSError("injected compensation failure")
        real_replace(source, destination)

    monkeypatch.setattr(upgrade_ops.os, "replace", fail_preserving_old)
    monkeypatch.setattr(
        upgrade_ops,
        "_write_manifest",
        lambda path, payload: (_ for _ in ()).throw(
            UpgradeOperationError("injected manifest failure")
        ),
    )

    with pytest.raises(UpgradeOperationError) as raised:
        rollback_launch_upgrade(
            server_directory=server,
            recovery_root=recovery_root,
            profile_id="profile-1",
            recovery_id=recovery.recovery_id,
            distribution="vanilla",
        )

    assert (server / "server.jar").read_bytes() == b"old server"
    server_displaced = next(server.glob(".blockstead-r-*-d"))
    assert server_displaced.read_bytes() == b"new server"
    assert (recovery.recovery_directory / "replaced-server.jar").read_bytes() == b"new server"
    assert str(recovery.recovery_directory) in str(raised.value)
