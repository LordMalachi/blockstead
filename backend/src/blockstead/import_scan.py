import json
import shutil
import time
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from .distributions import detect_distribution

UPLOAD_PREFIX = ".upload-"
STALE_UPLOAD_SECONDS = 24 * 60 * 60


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
            f"Blockstead can only scan folders inside {root}. To bring in a folder "
            "from somewhere else on this computer, use the dashboard's Import "
            "section to upload it instead."
        )
    return candidate


def safe_relative_path(name: str) -> PurePosixPath:
    """Turn an uploaded file's browser-supplied path into a safe relative path."""
    if not name or "\\" in name or "\x00" in name:
        raise ValueError("The upload contained a file with an unusable name.")
    parts = [part for part in name.split("/") if part and part != "."]
    if not parts or ".." in parts:
        raise ValueError("The upload contained a file path that leaves the server folder.")
    return PurePosixPath(*parts)


def promote_staging(staging: Path, target: Path) -> None:
    """Move a finished upload into place, unwrapping the folder the browser added.

    Folder uploads arrive with every path prefixed by the chosen folder's own
    name; when that single wrapper is all the staging area holds, its contents
    become the server folder so the world sits at the top level.
    """
    entries = list(staging.iterdir())
    source = staging
    if len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink():
        source = entries[0]
    if target.exists():
        raise ValueError(f"A server folder named {target.name} already exists.")
    source.rename(target)
    if source != staging:
        staging.rmdir()


def purge_stale_uploads(root: Path, older_than_seconds: float = STALE_UPLOAD_SECONDS) -> None:
    """Remove abandoned upload staging folders so they cannot accumulate."""
    cutoff = time.time() - older_than_seconds
    for entry in root.glob(f"{UPLOAD_PREFIX}*"):
        try:
            if entry.is_dir() and not entry.is_symlink() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def scan_server(path: Path, allowed_root: Path) -> ImportScan:
    folder = canonical_child(path, allowed_root)
    names = {entry.name for entry in folder.iterdir()}
    distribution = detect_distribution(folder)
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
