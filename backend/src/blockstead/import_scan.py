import json
from pathlib import Path

from pydantic import BaseModel


class ImportScan(BaseModel):
    canonical_path: str
    distribution: str
    minecraft_version: str | None
    detected_files: list[str]
    is_fixture: bool
    plan: list[str]


def canonical_child(path: Path, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    candidate = path.resolve(strict=True)
    if not candidate.is_dir() or (candidate != root and root not in candidate.parents):
        raise ValueError(
            "Server folder must be an existing directory inside the configured server root."
        )
    return candidate


def scan_server(path: Path, allowed_root: Path) -> ImportScan:
    folder = canonical_child(path, allowed_root)
    names = {entry.name for entry in folder.iterdir()}
    distribution = "unknown"
    if "paper.yml" in names or "paper-global.yml" in names:
        distribution = "paper"
    elif "fabric-server-launch.jar" in names:
        distribution = "fabric"
    elif any(name.startswith("neoforge-") and name.endswith(".jar") for name in names):
        distribution = "neoforge"
    elif "server.properties" in names and ("server.jar" in names or "fake-server.json" in names):
        distribution = "vanilla"
    version = None
    marker = folder / "fake-server.json"
    if marker.is_file():
        try:
            value = json.loads(marker.read_text(encoding="utf-8"))
            version = (
                str(value.get("minecraft_version")) if value.get("minecraft_version") else None
            )
        except (OSError, json.JSONDecodeError):
            pass
    detected = sorted(
        name
        for name in names
        if name
        in {
            "server.properties",
            "eula.txt",
            "world",
            "logs",
            "crash-reports",
            "plugins",
            "mods",
            "fake-server.json",
        }
        or name.endswith(".jar")
    )
    return ImportScan(
        canonical_path=str(folder),
        distribution=distribution,
        minecraft_version=version,
        detected_files=detected,
        is_fixture=marker.is_file(),
        plan=[
            "Leave the folder in place",
            "Do not change ownership or permissions",
            "Do not modify or launch imported files",
            "Create a Blockstead profile record only",
        ],
    )
