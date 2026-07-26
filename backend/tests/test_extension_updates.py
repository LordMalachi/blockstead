import hashlib
from pathlib import Path

import pytest

from blockstead.catalog import PlannedFile
from blockstead.extension_updates import (
    ExtensionRecoveryError,
    build_review,
    finalize_recovery,
    prepare_recovery,
    rollback_update,
)


def planned() -> list[PlannedFile]:
    return [
        PlannedFile(
            project_id="root",
            version_id="root-2",
            version_number="2.0",
            file_name="root-2.jar",
            url="https://example.test/root.jar",
            checksum_algorithm="sha512",
            checksum="a" * 128,
            required_by=None,
        ),
        PlannedFile(
            project_id="dep",
            version_id="dep-1",
            version_number="1.0",
            file_name="dep-1.jar",
            url="https://example.test/dep.jar",
            checksum_algorithm="sha512",
            checksum="b" * 128,
            required_by="root-2.jar",
        ),
    ]


def test_review_names_files_dependencies_java_restart_and_rollback() -> None:
    review = build_review(
        profile_id="profile-1",
        distribution="fabric",
        minecraft_version="1.21.6",
        required_java=21,
        installed_name="root-1.jar",
        installed_version="1.0",
        installed_sha512="c" * 128,
        planned=planned(),
        existing_names=frozenset(),
    )

    assert review.new_version_number == "2.0"
    assert review.required_java_major == 21
    assert review.restart_required is True
    assert review.dependencies == ["dep-1.jar"]
    assert [item.action for item in review.files] == ["replace", "install"]
    assert "exact replaced jar" in review.rollback_detail


def test_extension_recovery_restores_old_and_removes_reviewed_new_files(
    tmp_path: Path,
) -> None:
    extensions = tmp_path / "mods"
    extensions.mkdir()
    old = extensions / "root-1.jar"
    old.write_bytes(b"old")
    old_sha512 = hashlib.sha512(b"old").hexdigest()
    review = build_review(
        profile_id="profile-1",
        distribution="fabric",
        minecraft_version="1.21.6",
        required_java=21,
        installed_name=old.name,
        installed_version="1.0",
        installed_sha512=old_sha512,
        planned=planned(),
        existing_names=frozenset(),
    )
    recovery_id, recovery = prepare_recovery(
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        extension_directory=extensions,
        review=review,
        installed_sha512=old_sha512,
    )
    old.unlink()
    new_root = extensions / "root-2.jar"
    new_dependency = extensions / "dep-1.jar"
    new_root.write_bytes(b"new")
    new_dependency.write_bytes(b"dependency")
    finalize_recovery(
        recovery,
        new_files=[
            (new_root.name, "sha256", hashlib.sha256(b"new").hexdigest()),
            (
                new_dependency.name,
                "sha256",
                hashlib.sha256(b"dependency").hexdigest(),
            ),
        ],
    )

    rollback_update(
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        recovery_id=recovery_id,
        extension_directory=extensions,
    )

    assert old.read_bytes() == b"old"
    assert not new_root.exists()
    assert not new_dependency.exists()


def test_extension_recovery_refuses_a_changed_new_file(tmp_path: Path) -> None:
    extensions = tmp_path / "plugins"
    extensions.mkdir()
    old = extensions / "root-1.jar"
    old.write_bytes(b"old")
    old_sha512 = hashlib.sha512(b"old").hexdigest()
    review = build_review(
        profile_id="profile-1",
        distribution="paper",
        minecraft_version="1.21.6",
        required_java=21,
        installed_name=old.name,
        installed_version=None,
        installed_sha512=old_sha512,
        planned=planned()[:1],
        existing_names=frozenset(),
    )
    recovery_id, recovery = prepare_recovery(
        recovery_root=tmp_path / "data",
        profile_id="profile-1",
        extension_directory=extensions,
        review=review,
        installed_sha512=old_sha512,
    )
    old.unlink()
    new = extensions / "root-2.jar"
    new.write_bytes(b"new")
    finalize_recovery(
        recovery,
        new_files=[(new.name, "sha256", hashlib.sha256(b"new").hexdigest())],
    )
    new.write_bytes(b"changed")

    with pytest.raises(ExtensionRecoveryError, match="changed after the update"):
        rollback_update(
            recovery_root=tmp_path / "data",
            profile_id="profile-1",
            recovery_id=recovery_id,
            extension_directory=extensions,
        )
