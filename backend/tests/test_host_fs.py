import os
import stat
import sys
from pathlib import Path

import pytest

from blockstead.host_fs import (
    apply_mode,
    atomic_write_bytes,
    atomic_write_text,
    copy_mode,
    describe_os_error,
    fsync_path,
    remove_readonly,
    restrict_to_owner,
    rmtree,
)


def _listable_by_current_user(path: Path) -> bool:
    """Prove the directory is still usable: list it and create a file in it."""

    list(path.iterdir())
    probe = path / ".blockstead-listable-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return True


def test_restrict_to_owner_leaves_directory_listable_by_owner(tmp_path: Path) -> None:
    """The headline regression: hardening a directory must never lock its owner out.

    This is the exact shape of the reproduced defect: a directory written and
    then "hardened" by the application must remain readable by the account
    that owns it, on every platform, including Windows where a raw
    ``chmod(0o700)`` was observed to strip the owner's own ACE.
    """

    target = tmp_path / "private"
    target.mkdir()
    (target / "existing.txt").write_text("hello", encoding="utf-8")

    restrict_to_owner(target)

    assert _listable_by_current_user(target)
    assert (target / "existing.txt").read_text(encoding="utf-8") == "hello"


def test_restrict_to_owner_leaves_file_readable(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.write_text("hello", encoding="utf-8")

    restrict_to_owner(target)

    assert target.read_text(encoding="utf-8") == "hello"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on POSIX")
def test_restrict_to_owner_sets_posix_mode_bits(tmp_path: Path) -> None:
    directory = tmp_path / "dir"
    directory.mkdir()
    file_ = tmp_path / "file.txt"
    file_.write_text("x", encoding="utf-8")

    restrict_to_owner(directory)
    restrict_to_owner(file_)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(file_.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on POSIX")
def test_restrict_to_owner_with_fd_uses_fchmod(tmp_path: Path) -> None:
    target = tmp_path / "handle.txt"
    with target.open("xb") as handle:
        restrict_to_owner(target, fd=handle.fileno())
        handle.write(b"data")

    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on POSIX")
def test_copy_mode_preserves_source_permission_bits(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    source.chmod(0o640)
    target = tmp_path / "target.txt"
    target.write_text("y", encoding="utf-8")
    target.chmod(0o777)

    copy_mode(source, target)

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only apply on POSIX")
def test_apply_mode_sets_exact_bits(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")

    apply_mode(target, 0o750)

    assert stat.S_IMODE(target.stat().st_mode) == 0o750


@pytest.mark.skipif(sys.platform != "win32", reason="asserts the Windows no-op specifically")
def test_apply_mode_is_a_documented_noop_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "f.txt"
    target.write_text("x", encoding="utf-8")
    calls: list[int] = []
    monkeypatch.setattr(Path, "chmod", lambda self, mode: calls.append(mode))

    apply_mode(target, 0o700)

    assert calls == []


def test_atomic_write_bytes_creates_file_with_content(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    atomic_write_bytes(target, b"hello world")
    assert target.read_bytes() == b"hello world"


def test_atomic_write_text_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "content")
    leftovers = [entry for entry in tmp_path.iterdir() if entry != target]
    assert leftovers == []


def test_atomic_write_preserves_old_content_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-write must never leave a truncated destination file.

    Simulates a failure between staging the new content and the final
    ``os.replace`` (e.g. disk full, or a permissions problem) and asserts the
    previous content is untouched and no partial temp file survives.
    """

    target = tmp_path / "server.properties"
    target.write_text("level-name=old-world\n", encoding="utf-8")

    real_replace = os.replace

    def failing_replace(src: object, dst: object) -> None:
        raise OSError("simulated disk failure during replace")

    monkeypatch.setattr("blockstead.host_fs.os.replace", failing_replace)

    with pytest.raises(OSError, match="simulated disk failure"):
        atomic_write_text(target, "level-name=new-world\n")

    monkeypatch.setattr("blockstead.host_fs.os.replace", real_replace)
    assert target.read_text(encoding="utf-8") == "level-name=old-world\n"
    leftovers = [entry for entry in tmp_path.iterdir() if entry != target]
    assert leftovers == []


def test_atomic_write_before_replace_hook_runs_on_staging_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    seen: list[Path] = []

    def hook(staging: Path) -> None:
        seen.append(staging)
        assert staging.read_bytes() == b"payload"
        assert staging != target

    atomic_write_bytes(target, b"payload", before_replace=hook)

    assert len(seen) == 1
    assert target.read_bytes() == b"payload"


def test_atomic_write_before_replace_failure_aborts_and_cleans_up(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    def hook(staging: Path) -> None:
        raise ValueError("conflict detected")

    with pytest.raises(ValueError, match="conflict detected"):
        atomic_write_bytes(target, b"new", before_replace=hook)

    assert target.read_text(encoding="utf-8") == "original"
    leftovers = [entry for entry in tmp_path.iterdir() if entry != target]
    assert leftovers == []


def test_fsync_path_accepts_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "f.bin"
    target.write_bytes(b"data")
    fsync_path(target)  # must not raise


def test_remove_readonly_reraises_non_permission_errors() -> None:
    def boom(path: str) -> None:
        raise AssertionError("should not be called")

    with pytest.raises(FileNotFoundError):
        remove_readonly(boom, "missing", FileNotFoundError("gone"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only read-only retry path")
def test_rmtree_removes_a_readonly_file(tmp_path: Path) -> None:
    directory = tmp_path / "tree"
    directory.mkdir()
    readonly_file = directory / "locked.txt"
    readonly_file.write_text("x", encoding="utf-8")
    readonly_file.chmod(stat.S_IREAD)

    try:
        rmtree(directory)
    finally:
        # Best-effort: if rmtree somehow failed to clear the bit, do not
        # leave a read-only file behind for the test runner to trip over.
        if readonly_file.exists():
            readonly_file.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert not directory.exists()


def test_rmtree_raises_when_directory_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        rmtree(tmp_path / "does-not-exist")


def test_describe_os_error_permission_error_names_the_path(tmp_path: Path) -> None:
    target = tmp_path / "locked" / "file.txt"
    message = describe_os_error(PermissionError(13, "Permission denied"), target)
    assert str(target) in message
    assert "permission" in message.lower()


def test_describe_os_error_windows_sharing_violation_mentions_the_server(tmp_path: Path) -> None:
    target = tmp_path / "server.properties"
    exc = PermissionError(13, "The process cannot access the file")
    exc.winerror = 32  # type: ignore[attr-defined]
    message = describe_os_error(exc, target)
    assert "running" in message.lower()
    assert "stop" in message.lower()


def test_describe_os_error_file_not_found_names_the_path(tmp_path: Path) -> None:
    target = tmp_path / "missing.txt"
    message = describe_os_error(FileNotFoundError(2, "No such file or directory"), target)
    assert str(target) in message
    assert "not found" in message.lower()


def test_describe_os_error_never_mentions_errno_jargon(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    for exc in (
        PermissionError(13, "Permission denied"),
        FileNotFoundError(2, "No such file or directory"),
        OSError(28, "No space left on device"),
    ):
        message = describe_os_error(exc, target)
        assert "errno" not in message.lower()
        assert "winerror" not in message.lower()
