"""Distribution adapters for recognized server folder layouts.

Recognition and launch planning only ever read the folder; nothing here
executes, moves, or rewrites imported files.
"""

import os
from dataclasses import dataclass
from pathlib import Path


class LaunchPlanError(ValueError):
    """The folder does not contain a launchable layout for its distribution."""


@dataclass(frozen=True)
class DistributionInfo:
    key: str
    label: str
    extension_directory: str | None  # "plugins", "mods", or None


DISTRIBUTIONS: dict[str, DistributionInfo] = {
    "vanilla": DistributionInfo("vanilla", "Vanilla Minecraft", None),
    "paper": DistributionInfo("paper", "Paper", "plugins"),
    "fabric": DistributionInfo("fabric", "Fabric", "mods"),
    "forge": DistributionInfo("forge", "Forge", "mods"),
    "quilt": DistributionInfo("quilt", "Quilt", "mods"),
    "neoforge": DistributionInfo("neoforge", "NeoForge", "mods"),
    "unknown": DistributionInfo("unknown", "Unknown", None),
}

PAPER_MARKERS = frozenset({"paper.yml", "paper-global.yml", "config"})


def detect_distribution(folder: Path) -> str:
    """Classify a server folder by its marker files. Read-only."""
    names = {entry.name for entry in folder.iterdir()}
    if "paper.yml" in names or "paper-global.yml" in names:
        return "paper"
    if (folder / "config" / "paper-global.yml").is_file():
        return "paper"
    if "fabric-server-launch.jar" in names or "fabric-server-launcher.properties" in names:
        return "fabric"
    if "quilt-server-launch.jar" in names or "quilt-server-launcher.properties" in names:
        return "quilt"
    if any(name.startswith("neoforge-") and name.endswith(".jar") for name in names):
        return "neoforge"
    if (folder / "libraries" / "net" / "neoforged" / "neoforge").is_dir():
        return "neoforge"
    if any(name.startswith("forge-") and name.endswith(".jar") for name in names):
        return "forge"
    if (folder / "libraries" / "net" / "minecraftforge" / "forge").is_dir():
        return "forge"
    if "server.properties" in names and ("server.jar" in names or "fake-server.json" in names):
        return "vanilla"
    return "unknown"


def _version_tuple(minecraft_version: str) -> tuple[int, ...] | None:
    parts = minecraft_version.strip().split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def required_java_major(minecraft_version: str | None) -> int | None:
    """Minimum Java major version for a Minecraft version, or None if unknown."""
    if minecraft_version is None:
        return None
    version = _version_tuple(minecraft_version)
    if version is None or len(version) < 2:
        return None
    if version >= (1, 20, 5):
        return 21
    if version >= (1, 18):
        return 17
    if version >= (1, 17):
        return 16
    return 8


def _single_top_level_jar(folder: Path, exclude: frozenset[str] = frozenset()) -> Path:
    jars = sorted(
        entry
        for entry in folder.iterdir()
        if entry.is_file() and entry.suffix == ".jar" and entry.name not in exclude
    )
    if not jars:
        raise LaunchPlanError("No server jar was found in this folder.")
    if len(jars) > 1:
        raise LaunchPlanError(
            "Multiple jar files were found; Blockstead cannot decide which one is the server."
        )
    return jars[0]


def _loader_args_file(folder: Path, distribution: str) -> Path:
    coordinates = {
        "forge": ("minecraftforge", "forge"),
        "neoforge": ("neoforged", "neoforge"),
    }
    group, artifact = coordinates[distribution]
    base = folder / "libraries" / "net" / group / artifact
    file_name = "win_args.txt" if os.name == "nt" else "unix_args.txt"
    candidates = sorted(base.glob(f"*/{file_name}")) if base.is_dir() else []
    if not candidates:
        raise LaunchPlanError(
            f"This {DISTRIBUTIONS[distribution].label} folder has no installed launch files. "
            f"Run the {DISTRIBUTIONS[distribution].label} installer in it first."
        )
    if len(candidates) > 1:
        raise LaunchPlanError(
            f"Multiple {DISTRIBUTIONS[distribution].label} versions are installed in this "
            "folder; remove all but one."
        )
    return candidates[0]


def launch_arguments(
    distribution: str, folder: Path, java_executable: str = "java"
) -> tuple[str, ...]:
    """Build the exec argument array for a recognized distribution.

    Raises LaunchPlanError when the folder cannot be launched as-is.
    """
    if distribution == "vanilla":
        jar = folder / "server.jar"
        if not jar.is_file():
            raise LaunchPlanError("This vanilla profile does not contain server.jar.")
        return (java_executable, "-jar", str(jar), "nogui")
    if distribution == "paper":
        jar = folder / "server.jar"
        if not jar.is_file():
            jar = _single_top_level_jar(folder)
        return (java_executable, "-jar", str(jar), "nogui")
    if distribution == "fabric":
        jar = folder / "fabric-server-launch.jar"
        if not jar.is_file():
            raise LaunchPlanError("This Fabric profile does not contain fabric-server-launch.jar.")
        return (java_executable, "-jar", str(jar), "nogui")
    if distribution == "quilt":
        jar = folder / "quilt-server-launch.jar"
        if not jar.is_file():
            raise LaunchPlanError("This Quilt profile does not contain quilt-server-launch.jar.")
        return (java_executable, "-jar", str(jar), "nogui")
    if distribution in {"forge", "neoforge"}:
        try:
            args_file = _loader_args_file(folder, distribution)
        except LaunchPlanError:
            # Forge 1.16 and older used a directly launchable universal/server jar.
            if distribution != "forge":
                raise
            legacy = sorted(
                entry
                for entry in folder.glob("forge-*.jar")
                if "installer" not in entry.name and entry.is_file()
            )
            if len(legacy) == 1:
                return (java_executable, "-jar", str(legacy[0]), "nogui")
            raise
        arguments = [java_executable]
        if (folder / "user_jvm_args.txt").is_file():
            arguments.append("@user_jvm_args.txt")
        arguments.extend((f"@{args_file.relative_to(folder).as_posix()}", "nogui"))
        return tuple(arguments)
    raise LaunchPlanError("Blockstead does not know how to launch this distribution.")
