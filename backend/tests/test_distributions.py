from pathlib import Path

import pytest

from blockstead.distributions import (
    LaunchPlanError,
    detect_distribution,
    launch_arguments,
    required_java_major,
)
from blockstead.java_runtime import JavaRuntime, _parse_major, find_java


def make_folder(tmp_path: Path, *names: str) -> Path:
    folder = tmp_path / "server"
    folder.mkdir()
    for name in names:
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    return folder


def test_detects_paper(tmp_path: Path) -> None:
    folder = make_folder(tmp_path, "paper.jar", "config/paper-global.yml", "server.properties")
    assert detect_distribution(folder) == "paper"


def test_detects_fabric(tmp_path: Path) -> None:
    folder = make_folder(tmp_path, "fabric-server-launch.jar", "server.properties")
    assert detect_distribution(folder) == "fabric"


def test_detects_neoforge_by_libraries(tmp_path: Path) -> None:
    folder = make_folder(
        tmp_path, "libraries/net/neoforged/neoforge/21.1.77/unix_args.txt", "server.properties"
    )
    assert detect_distribution(folder) == "neoforge"


def test_detects_vanilla_and_unknown(tmp_path: Path) -> None:
    vanilla = make_folder(tmp_path, "server.properties", "server.jar")
    assert detect_distribution(vanilla) == "vanilla"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_distribution(empty) == "unknown"


def test_required_java_major_mapping() -> None:
    assert required_java_major("1.16.5") == 8
    assert required_java_major("1.17.1") == 16
    assert required_java_major("1.18") == 17
    assert required_java_major("1.20.4") == 17
    assert required_java_major("1.20.5") == 21
    assert required_java_major("1.21.1") == 21
    assert required_java_major(None) is None
    assert required_java_major("weird") is None


def test_launch_arguments_vanilla_and_fabric(tmp_path: Path) -> None:
    vanilla = make_folder(tmp_path, "server.jar")
    args = launch_arguments("vanilla", vanilla, "/opt/java/bin/java")
    assert args[0] == "/opt/java/bin/java" and args[-1] == "nogui"
    fabric = tmp_path / "fabric"
    fabric.mkdir()
    with pytest.raises(LaunchPlanError, match="fabric-server-launch.jar"):
        launch_arguments("fabric", fabric)


def test_launch_arguments_paper_requires_unambiguous_jar(tmp_path: Path) -> None:
    folder = make_folder(tmp_path, "paper-1.21.jar")
    assert str(folder / "paper-1.21.jar") in launch_arguments("paper", folder)
    (folder / "second.jar").write_text("", encoding="utf-8")
    with pytest.raises(LaunchPlanError, match="Multiple jar files"):
        launch_arguments("paper", folder)


def test_launch_arguments_neoforge_uses_args_file(tmp_path: Path) -> None:
    folder = make_folder(
        tmp_path,
        "libraries/net/neoforged/neoforge/21.1.77/unix_args.txt",
        "libraries/net/neoforged/neoforge/21.1.77/win_args.txt",
        "user_jvm_args.txt",
    )
    args = launch_arguments("neoforge", folder)
    assert "@user_jvm_args.txt" in args
    assert any(arg.startswith("@libraries/") for arg in args)
    with pytest.raises(LaunchPlanError, match="does not know"):
        launch_arguments("unknown", folder)


def test_java_major_parsing() -> None:
    assert _parse_major("1.8.0_392") == 8
    assert _parse_major("17.0.9") == 17
    assert _parse_major("21") == 21
    assert _parse_major("junk") is None


def test_find_java_picks_lowest_satisfying() -> None:
    runtimes = [
        JavaRuntime(path="/j8", version="1.8.0", major=8),
        JavaRuntime(path="/j17", version="17.0.9", major=17),
        JavaRuntime(path="/j21", version="21.0.2", major=21),
    ]
    assert find_java(17, runtimes) is not None
    assert find_java(17, runtimes).path == "/j17"  # type: ignore[union-attr]
    assert find_java(22, runtimes) is None
    assert find_java(None, runtimes).path == "/j21"  # type: ignore[union-attr]
    assert find_java(None, []) is None
