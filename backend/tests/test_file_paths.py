import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from blockstead.file_paths import (
    FilePathError,
    category_root,
    extract_zip_safely,
    is_editable_text,
    list_directory,
    promote_extracted,
    resolve_target,
    resolve_within,
)


def test_resolve_within_rejects_traversal_and_absolute(tmp_path: Path) -> None:
    for unsafe in ("../escape.txt", "a/../../b.txt", "/etc/passwd", "a\x00b", "", "."):
        with pytest.raises(FilePathError):
            resolve_within(tmp_path, unsafe)


def test_resolve_within_rejects_backslash_and_dot_leading(tmp_path: Path) -> None:
    with pytest.raises(FilePathError):
        resolve_within(tmp_path, "a\\..\\b.txt")
    with pytest.raises(FilePathError):
        resolve_within(tmp_path, ".hidden/file.txt")


def test_resolve_within_rejects_symlink_component(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(FilePathError):
        resolve_within(root, "link/secret.txt")


def test_resolve_within_allows_nested_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    resolved = resolve_within(root, "sub/file.txt")
    assert resolved == root / "sub" / "file.txt"


def test_category_root_config_and_logs(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    config_root = category_root(server_directory, "vanilla", "config")
    assert config_root.base == server_directory
    assert config_root.allowed_top_level is None
    logs_root = category_root(server_directory, "vanilla", "logs")
    assert logs_root.base == server_directory / "logs"


def test_config_category_excludes_world_logs_and_extension_folders(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    (server_directory / "world").mkdir(parents=True)
    (server_directory / "logs").mkdir()
    (server_directory / "mods").mkdir()
    (server_directory / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    root = category_root(server_directory, "fabric", "config")
    names = {entry.name for entry in list_directory(root)}
    assert names == {"server.properties"}
    with pytest.raises(FilePathError):
        resolve_target(root, "world/level.dat")
    with pytest.raises(FilePathError):
        resolve_target(root, "logs/latest.log")
    with pytest.raises(FilePathError):
        resolve_target(root, "mods/some.jar")
    # A nested subfolder that is not one of the excluded names stays reachable.
    (server_directory / "config").mkdir()
    expected = server_directory / "config" / "example.toml"
    assert resolve_target(root, "config/example.toml") == expected


def test_category_root_extensions_raises_for_vanilla(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    with pytest.raises(FilePathError):
        category_root(server_directory, "vanilla", "extensions")


def test_category_root_extensions_resolves_for_fabric(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    root = category_root(server_directory, "fabric", "extensions")
    assert root.base == server_directory / "mods"


def test_category_root_world_lists_recognized_folders_only(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    (server_directory / "world").mkdir()
    (server_directory / "world_nether").mkdir()
    (server_directory / "logs").mkdir()
    root = category_root(server_directory, "vanilla", "world")
    assert root.allowed_top_level == frozenset({"world", "world_nether"})


def test_category_root_backups_requires_data_dir_and_profile_id(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    with pytest.raises(FilePathError):
        category_root(server_directory, "vanilla", "backups")
    root = category_root(
        server_directory, "vanilla", "backups", data_dir=tmp_path / "data", profile_id="p1"
    )
    assert root.base == tmp_path / "data" / "backups" / "p1"


def test_resolve_target_rejects_path_outside_world_folders(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    (server_directory / "world").mkdir(parents=True)
    (server_directory / "logs").mkdir()
    root = category_root(server_directory, "vanilla", "world")
    with pytest.raises(FilePathError):
        resolve_target(root, "logs/latest.log")
    assert resolve_target(root, "world/level.dat") == server_directory / "world" / "level.dat"


def test_list_directory_excludes_symlinks_and_dotfiles(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    server_directory.mkdir()
    (server_directory / "visible.properties").write_text("a=b\n", encoding="utf-8")
    (server_directory / ".hidden").write_text("x", encoding="utf-8")
    (server_directory / "real.txt").write_text("y", encoding="utf-8")
    (server_directory / "link.txt").symlink_to(server_directory / "real.txt")
    root = category_root(server_directory, "vanilla", "config")
    entries = list_directory(root)
    names = {entry.name for entry in entries}
    assert names == {"visible.properties", "real.txt"}


def test_list_directory_world_root_shows_only_recognized_folders(tmp_path: Path) -> None:
    server_directory = tmp_path / "server"
    (server_directory / "world").mkdir(parents=True)
    (server_directory / "not_a_world").mkdir()
    root = category_root(server_directory, "vanilla", "world")
    entries = list_directory(root)
    names = {entry.name for entry in entries}
    assert names == {"world"}


def test_is_editable_text_respects_read_only_categories() -> None:
    viewable, editable = is_editable_text("logs", "latest.log", 100)
    assert viewable is True
    assert editable is False
    viewable, editable = is_editable_text("config", "server.properties", 100)
    assert viewable is True
    assert editable is True
    viewable, editable = is_editable_text("config", "server.jar", 100)
    assert viewable is False
    assert editable is False


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_extract_zip_safely_rejects_path_traversal_member(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = tmp_path / "evil.zip"
    archive_path.write_bytes(_zip_bytes({"../escape.txt": b"pwned"}))
    with pytest.raises(FilePathError):
        extract_zip_safely(archive_path, destination)
    assert not any(destination.iterdir())


def test_extract_zip_safely_enforces_file_count_cap(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = tmp_path / "many.zip"
    archive_path.write_bytes(_zip_bytes({f"file{i}.txt": b"x" for i in range(5)}))
    with pytest.raises(FilePathError):
        extract_zip_safely(archive_path, destination, max_files=3)
    assert not any(destination.iterdir())


def test_extract_zip_safely_enforces_total_bytes_cap(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = tmp_path / "big.zip"
    archive_path.write_bytes(_zip_bytes({"big.bin": b"x" * 1000}))
    with pytest.raises(FilePathError):
        extract_zip_safely(archive_path, destination, max_total_bytes=100)
    assert not any(destination.iterdir())


def test_extract_zip_safely_rejects_empty_archive(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = tmp_path / "empty.zip"
    archive_path.write_bytes(_zip_bytes({}))
    with pytest.raises(FilePathError):
        extract_zip_safely(archive_path, destination)


def test_extract_zip_safely_and_promote_writes_files(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    archive_path = tmp_path / "pack.zip"
    archive_path.write_bytes(_zip_bytes({"a.txt": b"one", "sub/b.txt": b"two"}))
    staging = extract_zip_safely(archive_path, destination)
    promoted, preserved = promote_extracted(staging, destination, datetime.now(UTC))
    assert set(promoted) == {"a.txt", "sub"}
    assert preserved == []
    assert (destination / "a.txt").read_bytes() == b"one"
    assert (destination / "sub" / "b.txt").read_bytes() == b"two"
    assert not staging.exists()


def test_promote_extracted_preserves_name_collision(tmp_path: Path) -> None:
    destination = tmp_path / "dest"
    destination.mkdir()
    (destination / "a.txt").write_text("original", encoding="utf-8")
    archive_path = tmp_path / "pack.zip"
    archive_path.write_bytes(_zip_bytes({"a.txt": b"new"}))
    staging = extract_zip_safely(archive_path, destination)
    promoted, preserved = promote_extracted(staging, destination, datetime.now(UTC))
    assert promoted == ["a.txt"]
    assert len(preserved) == 1
    assert (destination / "a.txt").read_bytes() == b"new"
    assert (destination / preserved[0]).read_text(encoding="utf-8") == "original"
