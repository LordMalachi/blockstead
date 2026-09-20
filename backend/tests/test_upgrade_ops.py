import hashlib
from pathlib import Path

import pytest

import blockstead.upgrade_ops as upgrade_ops
from blockstead.upgrade_ops import (
    UpgradeOperationError,
    active_launch_file,
    create_upgrade_staging,
    promote_launch_upgrade,
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
        is_recovery_copy = (
            source.name == "server.jar"
            and source.parent.parent.parent.parent == recovery_root
        )
        if is_recovery_copy and destination == server / "server.jar":
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
    calls = 0

    def fail_preserving_old(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
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
    assert (recovery.recovery_directory / "replaced-server.jar").read_bytes() == b"new server"
    assert str(recovery.recovery_directory) in str(raised.value)
