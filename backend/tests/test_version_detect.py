import json
import zipfile
from pathlib import Path

from blockstead.import_scan import scan_server
from blockstead.version_detect import detect_minecraft_version


def write_server_jar(folder: Path, name: str = "server.jar", version: str = "1.21.4") -> None:
    with zipfile.ZipFile(folder / name, "w") as archive:
        archive.writestr("version.json", json.dumps({"id": version, "name": version}))


def test_version_comes_from_the_server_jar(tmp_path: Path) -> None:
    write_server_jar(tmp_path)
    assert detect_minecraft_version(tmp_path) == "1.21.4"


def test_plain_server_jar_wins_over_a_launcher_jar(tmp_path: Path) -> None:
    write_server_jar(tmp_path, "aaa-launcher.jar", "1.16.5")
    write_server_jar(tmp_path, "server.jar", "1.21.4")
    assert detect_minecraft_version(tmp_path) == "1.21.4"


def test_paper_history_identifies_the_folder(tmp_path: Path) -> None:
    (tmp_path / "version_history.json").write_text(
        json.dumps({"currentVersion": "git-Paper-497 (MC: 1.20.6)"}), encoding="utf-8"
    )
    assert detect_minecraft_version(tmp_path) == "1.20.6"


def test_logs_identify_a_folder_with_no_readable_jar(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "latest.log").write_text(
        "[12:00:00] [main/INFO]: Starting minecraft server version 1.19.2\n"
        "[12:00:01] [main/INFO]: Loading properties\n",
        encoding="utf-8",
    )
    assert detect_minecraft_version(tmp_path) == "1.19.2"


def test_damaged_and_unfamiliar_folders_read_as_unknown(tmp_path: Path) -> None:
    (tmp_path / "server.jar").write_bytes(b"not a zip file")
    (tmp_path / "version_history.json").write_text("{ broken", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "latest.log").write_text("nothing useful here\n", encoding="utf-8")
    assert detect_minecraft_version(tmp_path) is None


def test_a_hostile_version_string_is_refused(tmp_path: Path) -> None:
    # A version reaches provisioning and path building, so anything that is not
    # a plain version is not a version.
    with zipfile.ZipFile(tmp_path / "server.jar", "w") as archive:
        archive.writestr("version.json", json.dumps({"id": "../../etc/passwd"}))
    assert detect_minecraft_version(tmp_path) is None


def test_only_the_opening_lines_of_a_log_are_read(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "latest.log").write_text(
        "filler\n" * 5000 + "Starting minecraft server version 1.8.9\n", encoding="utf-8"
    )
    assert detect_minecraft_version(tmp_path) is None


def test_import_scan_records_the_detected_version(tmp_path: Path) -> None:
    folder = tmp_path / "my-server"
    folder.mkdir()
    (folder / "server.properties").write_text("motd=hi\n", encoding="utf-8")
    write_server_jar(folder)
    result = scan_server(folder, tmp_path)
    assert result.distribution == "vanilla"
    assert result.minecraft_version == "1.21.4"
    assert result.is_fixture is False


def test_import_scan_still_reads_the_fixture_marker() -> None:
    root = Path(__file__).parents[2] / "fixtures" / "servers"
    result = scan_server(root / "vanilla-fixture", root)
    assert result.is_fixture is True
    assert result.minecraft_version
