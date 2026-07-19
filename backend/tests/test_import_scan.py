import os
from pathlib import Path

import pytest

from blockstead.import_scan import (
    canonical_child,
    promote_staging,
    purge_stale_uploads,
    safe_relative_path,
    scan_server,
)


def test_fixture_scan_is_read_only() -> None:
    root = Path(__file__).parents[2] / "fixtures" / "servers"
    fixture = root / "vanilla-fixture"
    before = {path.relative_to(fixture): path.stat().st_mtime_ns for path in fixture.rglob("*")}
    result = scan_server(fixture, root)
    after = {path.relative_to(fixture): path.stat().st_mtime_ns for path in fixture.rglob("*")}
    assert result.distribution == "vanilla" and result.is_fixture is True
    assert before == after


def test_paths_cannot_escape_allowed_root(tmp_path: Path) -> None:
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    with pytest.raises(ValueError, match="can only scan folders inside"):
        canonical_child(outside, allowed)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        canonical_child(allowed / "link", allowed)


def test_safe_relative_path_keeps_nested_names() -> None:
    assert str(safe_relative_path("My Server/world/level.dat")) == "My Server/world/level.dat"
    assert str(safe_relative_path("server.properties")) == "server.properties"


@pytest.mark.parametrize("name", ["", "../evil", "a/../../b", "a\\b", "a\x00b", "..", "./."])
def test_safe_relative_path_rejects_escapes(name: str) -> None:
    with pytest.raises(ValueError):
        safe_relative_path(name)


def test_promote_staging_unwraps_single_folder(tmp_path: Path) -> None:
    staging = tmp_path / ".upload-abc"
    (staging / "JAR FILES" / "world").mkdir(parents=True)
    (staging / "JAR FILES" / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    target = tmp_path / "my-server"
    promote_staging(staging, target)
    assert (target / "server.properties").is_file()
    assert (target / "world").is_dir()
    assert not staging.exists()


def test_promote_staging_keeps_flat_uploads(tmp_path: Path) -> None:
    staging = tmp_path / ".upload-abc"
    staging.mkdir()
    (staging / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    (staging / "server.jar").write_bytes(b"jar")
    target = tmp_path / "my-server"
    promote_staging(staging, target)
    assert (target / "server.properties").is_file()
    assert not staging.exists()


def test_promote_staging_refuses_existing_target(tmp_path: Path) -> None:
    staging = tmp_path / ".upload-abc"
    staging.mkdir()
    (staging / "server.jar").write_bytes(b"jar")
    target = tmp_path / "my-server"
    target.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        promote_staging(staging, target)


def test_purge_stale_uploads_removes_only_old_staging(tmp_path: Path) -> None:
    stale, fresh, unrelated = tmp_path / ".upload-old", tmp_path / ".upload-new", tmp_path / "kept"
    for folder in (stale, fresh, unrelated):
        folder.mkdir()
    old = 1_000_000
    os.utime(stale, (old, old))
    purge_stale_uploads(tmp_path)
    assert not stale.exists()
    assert fresh.exists() and unrelated.exists()
