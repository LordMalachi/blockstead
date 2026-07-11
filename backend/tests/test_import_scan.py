from pathlib import Path

import pytest

from blockstead.import_scan import canonical_child, scan_server


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
    with pytest.raises(ValueError, match="inside the configured server root"):
        canonical_child(outside, allowed)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        canonical_child(allowed / "link", allowed)
