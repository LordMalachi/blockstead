"""Shared path safety for the safe file workspace.

Every list, read, write, upload, rename, delete, and archive-extract
operation the file workspace performs resolves its target through this
module before touching disk, so traversal and symlink-escape checks live in
one place instead of being reimplemented per category. Only five approved
path categories exist per profile (config, logs, extensions, world,
backups); there is no general filesystem browser.
"""

import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal

from .backups import backup_directory, world_roots
from .distributions import DISTRIBUTIONS
from .mod_configs import EDITABLE_SUFFIXES

FileCategory = Literal["config", "logs", "extensions", "world", "backups"]
CATEGORIES: tuple[FileCategory, ...] = ("config", "logs", "extensions", "world", "backups")

#: Categories where content is never editable or uploadable, download only.
READ_ONLY_CATEGORIES: frozenset[str] = frozenset({"logs", "backups"})
TEXT_SUFFIXES = EDITABLE_SUFFIXES | frozenset({".log"})
MAX_TEXT_BYTES = 1_000_000
MAX_EXTRACT_FILES = 5000
#: World archives can be large; this is a hard ceiling, not a typical size.
MAX_EXTRACT_BYTES = 2 * 1024 * 1024 * 1024
_STAGING_NAME = ".blockstead-extract.partial"


class FilePathError(ValueError):
    """A requested file-workspace path or operation was unsafe; message is user-safe."""


def resolve_within(root: Path, relative: str) -> Path:
    """Resolve a browser-supplied relative path strictly inside ``root``.

    Rejects absolute paths, ``..``, empty or dot-leading segments,
    backslashes, NUL bytes, and any path component that is itself a symlink
    (even one that would resolve back inside ``root``) — the workspace never
    edits or replaces a file through a symlink.
    """
    if not relative or "\x00" in relative:
        raise FilePathError("That file path is not usable.")
    posix = PurePosixPath(relative.replace("\\", "/"))
    if posix.is_absolute() or not posix.parts or any(
        part in {"", ".", ".."} or part.startswith(".") for part in posix.parts
    ):
        raise FilePathError("That file path is not usable.")
    root_resolved = root.resolve()
    candidate = root_resolved
    for part in posix.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise FilePathError("That file path is not usable.")
    resolved = candidate.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise FilePathError("That file path is not usable.")
    return candidate


@dataclass(frozen=True)
class CategoryRoot:
    """Where a category's browsable entries live.

    For config/logs/extensions/backups this is one directory and every entry
    in it is visible. For world it is the server directory itself, but only
    the recognized world folders (Paper's per-dimension folders, or the
    vanilla ``world*`` convention) are visible at the top level — never an
    arbitrary top-level entry of the server folder.

    ``config`` shares the server directory as its base too, but the reverse
    problem applies: without ``excluded_top_level`` it would also reach the
    world, logs, and extension folders that have their own categories (and
    their own stopped-server / read-only protections), letting a request
    against ``config`` silently bypass them. Config excludes those names at
    the top level instead of allow-listing its own, since arbitrary
    server-specific top-level files (any loader's own config files, EULA,
    etc.) are otherwise all in scope.
    """

    category: FileCategory
    base: Path
    allowed_top_level: frozenset[str] | None
    excluded_top_level: frozenset[str] | None = None


def category_root(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> CategoryRoot:
    if category == "config":
        info = DISTRIBUTIONS.get(distribution, DISTRIBUTIONS["unknown"])
        excluded = {"logs", *(path.name for path in world_roots(server_directory))}
        if info.extension_directory:
            excluded.add(info.extension_directory)
        return CategoryRoot(category, server_directory, None, frozenset(excluded))
    if category == "logs":
        return CategoryRoot(category, server_directory / "logs", None)
    if category == "extensions":
        info = DISTRIBUTIONS.get(distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            raise FilePathError("This server distribution does not load plugins or mods.")
        return CategoryRoot(category, server_directory / info.extension_directory, None)
    if category == "world":
        names = frozenset(path.name for path in world_roots(server_directory))
        return CategoryRoot(category, server_directory, names)
    if category == "backups":
        if data_dir is None or profile_id is None:
            raise FilePathError("Backup archives are not available for this profile.")
        return CategoryRoot(category, backup_directory(data_dir, profile_id), None)
    raise FilePathError("That file category is not recognized.")  # pragma: no cover


def resolve_target(root: CategoryRoot, relative: str) -> Path:
    """Resolve a path within a category, additionally enforcing the world
    category's allowed top-level folder names and config's excluded ones."""

    resolved = resolve_within(root.base, relative)
    top = PurePosixPath(relative.replace("\\", "/")).parts[0]
    if root.allowed_top_level is not None and top not in root.allowed_top_level:
        raise FilePathError("That path is outside the recognized world folders.")
    if root.excluded_top_level is not None and top in root.excluded_top_level:
        raise FilePathError("That path belongs to a different file category.")
    return resolved


def is_editable_text(category: FileCategory, name: str, size: int) -> tuple[bool, bool]:
    """Returns (viewable, editable) for a text preview of a file this size."""

    viewable = size <= MAX_TEXT_BYTES and PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES
    editable = viewable and category not in READ_ONLY_CATEGORIES
    return viewable, editable


@dataclass(frozen=True)
class FileEntry:
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: str | None
    viewable: bool
    editable: bool


def list_directory(root: CategoryRoot, subpath: str = "") -> list[FileEntry]:
    """Non-recursive listing of one folder inside a category, closest match
    to how a file manager shows one level at a time."""

    if subpath:
        target = resolve_target(root, subpath)
        prefix = PurePosixPath(subpath)
    else:
        target = root.base
        prefix = PurePosixPath()
    if not target.is_dir() or target.is_symlink():
        return []
    entries: list[FileEntry] = []
    try:
        children = sorted(target.iterdir(), key=lambda entry: entry.name.lower())
    except OSError:
        return []
    for child in children:
        if child.is_symlink() or child.name.startswith("."):
            continue
        if not subpath and root.allowed_top_level is not None:
            if child.name not in root.allowed_top_level:
                continue
        if not subpath and root.excluded_top_level is not None:
            if child.name in root.excluded_top_level:
                continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        viewable, editable = (False, False) if is_dir else is_editable_text(
            root.category, child.name, stat.st_size
        )
        entries.append(
            FileEntry(
                name=child.name,
                path=(prefix / child.name).as_posix(),
                is_dir=is_dir,
                size_bytes=None if is_dir else stat.st_size,
                modified_at=datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc  # noqa: UP017
                ).isoformat(),
                viewable=viewable,
                editable=editable,
            )
        )
    return entries


def extract_zip_safely(
    archive_path: Path,
    destination: Path,
    *,
    max_files: int = MAX_EXTRACT_FILES,
    max_total_bytes: int = MAX_EXTRACT_BYTES,
) -> Path:
    """Validate and extract a zip archive into a private staging directory
    beside ``destination``. The caller promotes staging into place with
    :func:`promote_extracted` and is responsible for removing it on failure.

    Every member path is resolved through :func:`resolve_within` against the
    staging directory, so path traversal ("zip slip") is rejected the same
    way an uploaded relative path would be. ``zipfile`` has no equivalent to
    ``tarfile``'s ``data_filter``, so this per-member validation is the
    entire safety boundary for extraction, not a defense-in-depth layer.
    """

    if not destination.is_dir() or destination.is_symlink():
        raise FilePathError("That destination folder was not found.")
    staging = destination / _STAGING_NAME
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(mode=0o700)
    count = 0
    total = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                count += 1
                if count > max_files:
                    raise FilePathError(
                        "The archive contains more files than Blockstead accepts."
                    )
                member_target = resolve_within(staging, info.filename)
                total += info.file_size
                if total > max_total_bytes:
                    raise FilePathError(
                        "The archive's total size is larger than Blockstead accepts."
                    )
                member_target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, member_target.open("wb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)
        if count == 0:
            raise FilePathError("The archive is empty.")
    except FilePathError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise FilePathError("The archive could not be read or extracted.") from exc
    return staging


def promote_extracted(
    staging: Path, destination: Path, now: datetime
) -> tuple[list[str], list[str]]:
    """Move every staged top-level entry into ``destination``.

    A name that already exists at the destination is preserved as a
    ``<name>.pre-extract-<timestamp>`` sibling rather than overwritten, the
    same preserve-rename recovery pattern the Backup Center uses for a world
    swap. Returns (promoted_names, preserved_names).
    """

    stamp = now.strftime("pre-extract-%Y%m%d-%H%M%S")
    promoted: list[str] = []
    preserved: list[str] = []
    try:
        for entry in sorted(staging.iterdir()):
            target = destination / entry.name
            if target.exists() or target.is_symlink():
                keep_name = f"{entry.name}.{stamp}"
                os.rename(target, destination / keep_name)
                preserved.append(keep_name)
            os.rename(entry, target)
            promoted.append(entry.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return promoted, preserved
