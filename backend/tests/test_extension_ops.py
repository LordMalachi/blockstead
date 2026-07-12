from pathlib import Path

import pytest

from blockstead.extension_ops import (
    ExtensionOpsError,
    disabled_directory,
    place_upload,
    remove,
    set_enabled,
)


@pytest.fixture
def mods(tmp_path: Path) -> Path:
    folder = tmp_path / "mods"
    folder.mkdir()
    (folder / "cool.jar").write_bytes(b"jar")
    return folder


def test_disable_and_enable_round_trip(mods: Path) -> None:
    target = set_enabled(mods, "cool.jar", enabled=False)
    assert target == disabled_directory(mods) / "cool.jar"
    assert not (mods / "cool.jar").exists()
    restored = set_enabled(mods, "cool.jar", enabled=True)
    assert restored == mods / "cool.jar" and restored.is_file()


def test_disable_refuses_collision(mods: Path) -> None:
    disabled = disabled_directory(mods)
    disabled.mkdir()
    (disabled / "cool.jar").write_bytes(b"other")
    with pytest.raises(ExtensionOpsError, match="already exists"):
        set_enabled(mods, "cool.jar", enabled=False)


def test_hostile_names_are_refused(mods: Path) -> None:
    for name in ("../escape.jar", "cool.jar/..", ".hidden.jar", "no-extension", "a\\b.jar"):
        with pytest.raises(ExtensionOpsError):
            set_enabled(mods, name, enabled=False)
        with pytest.raises(ExtensionOpsError):
            remove(mods, name)


def test_symlinked_jar_is_refused(mods: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.jar"
    outside.write_bytes(b"secret")
    (mods / "link.jar").symlink_to(outside)
    with pytest.raises(ExtensionOpsError, match="not found"):
        remove(mods, "link.jar")
    assert outside.exists()


def test_remove_deletes_only_the_named_file(mods: Path) -> None:
    (mods / "other.jar").write_bytes(b"jar")
    remove(mods, "cool.jar")
    assert not (mods / "cool.jar").exists()
    assert (mods / "other.jar").exists()


def test_upload_stages_and_refuses_duplicates(mods: Path) -> None:
    target = place_upload(mods, "new-mod.jar", b"uploaded")
    assert target.read_bytes() == b"uploaded"
    assert not list(mods.glob(".*.part"))
    with pytest.raises(ExtensionOpsError, match="already installed"):
        place_upload(mods, "new-mod.jar", b"again")
    with pytest.raises(ExtensionOpsError, match="empty"):
        place_upload(mods, "empty.jar", b"")
    with pytest.raises(ExtensionOpsError, match="jar"):
        place_upload(mods, "malware.exe", b"nope")
