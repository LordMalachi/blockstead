import hashlib
from pathlib import Path

import pytest

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
