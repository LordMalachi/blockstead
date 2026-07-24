import hashlib
import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from pydantic import BaseModel

from .file_paths import (
    MAX_TEXT_BYTES,
    READ_ONLY_CATEGORIES,
    CategoryRoot,
    FileCategory,
    FilePathError,
    category_root,
    extract_zip_safely,
    is_editable_text,
    list_directory,
    promote_extracted,
    resolve_target,
)
from .player_sessions import PlayerSessionInfo
from .server_settings import MAX_FILE_BYTES as MAX_FILE_BYTES
from .server_settings import read_settings as read_settings

#: Categories where a stopped server is required for a mutation. Config text
#: edits are safe on a running server the same way the settings editor is;
#: world and extension files are not.
STOPPED_REQUIRED_CATEGORIES: frozenset[str] = frozenset({"world", "extensions"})


class FileConflictError(RuntimeError):
    """The source file changed or disappeared before a safe write."""


class PlayerEntry(BaseModel):
    name: str
    uuid: str | None = None
    level: int | None = None
    reason: str | None = None


class PlayerFile(BaseModel):
    present: bool
    readable: bool
    players: list[PlayerEntry]


class PlayersView(BaseModel):
    allowlist: PlayerFile
    operators: PlayerFile
    bans: PlayerFile


def _read_limited(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_player_file(path: Path, *, ban_file: bool = False) -> PlayerFile:
    if not path.is_file():
        return PlayerFile(present=False, readable=False, players=[])
    text = _read_limited(path)
    if text is None:
        return PlayerFile(present=True, readable=False, players=[])
    try:
        records = json.loads(text)
    except json.JSONDecodeError:
        return PlayerFile(present=True, readable=False, players=[])
    if not isinstance(records, list):
        return PlayerFile(present=True, readable=False, players=[])
    players = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            continue
        uuid = record.get("uuid")
        level = record.get("level")
        reason = record.get("reason") if ban_file else None
        players.append(
            PlayerEntry(
                name=record["name"][:64],
                uuid=uuid if isinstance(uuid, str) else None,
                level=level if isinstance(level, int) else None,
                reason=reason[:200] if isinstance(reason, str) else None,
            )
        )
    return PlayerFile(present=True, readable=True, players=players)


def read_players(server_directory: Path) -> PlayersView:
    return PlayersView(
        allowlist=_read_player_file(server_directory / "whitelist.json"),
        operators=_read_player_file(server_directory / "ops.json"),
        bans=_read_player_file(server_directory / "banned-players.json", ban_file=True),
    )


class RosterEntry(BaseModel):
    name: str
    uuid: str | None
    online: bool | None
    allowlisted: bool
    operator: bool
    banned: bool
    ban_reason: str | None
    tracked_online: bool
    last_seen: str | None
    session_seconds: int | None


class RosterView(BaseModel):
    entries: list[RosterEntry]
    status_available: bool
    online_count: int | None
    max_players: int | None


def roster_names(players: PlayersView, status: dict[str, object] | None) -> list[str]:
    """Every player name the roster should show, in a stable first-seen order."""

    names: list[str] = []
    seen: set[str] = set()
    for group in (players.allowlist, players.operators, players.bans):
        for entry in group.players:
            if entry.name not in seen:
                seen.add(entry.name)
                names.append(entry.name)
    if status:
        sample = status.get("sample")
        if isinstance(sample, list):
            for name in sample:
                if isinstance(name, str) and name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


def build_roster(
    players: PlayersView,
    status: dict[str, object] | None,
    sessions: dict[str, PlayerSessionInfo],
) -> RosterView:
    sample = status.get("sample") if status else None
    online_names = (
        {name for name in sample if isinstance(name, str)} if isinstance(sample, list) else None
    )
    allow_by_name = {entry.name: entry for entry in players.allowlist.players}
    op_names = {entry.name for entry in players.operators.players}
    ban_by_name = {entry.name: entry for entry in players.bans.players}
    entries = []
    for name in roster_names(players, status):
        session = sessions.get(name)
        allow_entry = allow_by_name.get(name)
        ban_entry = ban_by_name.get(name)
        entries.append(
            RosterEntry(
                name=name,
                uuid=allow_entry.uuid if allow_entry else (ban_entry.uuid if ban_entry else None),
                online=(name in online_names) if online_names is not None else None,
                allowlisted=name in allow_by_name,
                operator=name in op_names,
                banned=name in ban_by_name,
                ban_reason=ban_entry.reason if ban_entry else None,
                tracked_online=session.tracked_online if session else False,
                last_seen=session.last_seen if session else None,
                session_seconds=session.session_seconds if session else None,
            )
        )
    online_count = status.get("online") if status else None
    max_players = status.get("max") if status else None
    return RosterView(
        entries=entries,
        status_available=status is not None,
        online_count=online_count if isinstance(online_count, int) else None,
        max_players=max_players if isinstance(max_players, int) else None,
    )


class FileNode(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int | None
    modified_at: str | None
    viewable: bool
    editable: bool


class FileListing(BaseModel):
    category: str
    path: str
    entries: list[FileNode]
    writable: bool
    stopped_required: bool


class FileContent(BaseModel):
    path: str
    content: str
    revision: str
    editable: bool


class FileEditPreview(BaseModel):
    revision: str
    valid: bool
    problems: list[str]
    no_changes: bool


class FileEditResult(BaseModel):
    path: str
    snapshot_name: str
    previous_revision: str
    revision: str


class RenameResult(BaseModel):
    path: str


class DeleteResult(BaseModel):
    snapshot_name: str | None
    preserved_name: str | None


class ArchiveExtractResult(BaseModel):
    promoted: list[str]
    preserved: list[str]


def _root(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    *,
    data_dir: Path | None,
    profile_id: str | None,
) -> CategoryRoot:
    return category_root(
        server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id
    )


def _require_writable(category: FileCategory) -> None:
    if category in READ_ONLY_CATEGORIES:
        raise FilePathError("This file category is read-only.")


def _is_protected_world_root(root: CategoryRoot, path: str) -> bool:
    """True when ``path`` is exactly a top-level world folder itself.

    World folders are only ever replaced through the Backup Center's verified
    restore; the file workspace can reach into them but never rename or
    delete the folder itself.
    """
    if root.allowed_top_level is None:
        return False
    parts = PurePosixPath(path).parts
    return len(parts) == 1 and parts[0] in root.allowed_top_level


def list_category(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    subpath: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> FileListing:
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    entries = list_directory(root, subpath)
    return FileListing(
        category=category,
        path=subpath,
        entries=[FileNode(**entry.__dict__) for entry in entries],
        writable=category not in READ_ONLY_CATEGORIES,
        stopped_required=category in STOPPED_REQUIRED_CATEGORIES,
    )


def resolve_download_path(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> Path:
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    target = resolve_target(root, path)
    if not target.is_file() or target.is_symlink():
        raise FilePathError("That file was not found.")
    return target


def read_file_content(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> FileContent:
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    target = resolve_target(root, path)
    if not target.is_file() or target.is_symlink():
        raise FilePathError("That file was not found.")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise FilePathError("That file could not be read.") from exc
    viewable, editable = is_editable_text(category, target.name, size)
    if not viewable:
        raise FilePathError("That file is too large or not a recognized text type to view.")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise FilePathError("That file could not be read.") from exc
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FilePathError("That file is not valid UTF-8 text.") from exc
    return FileContent(
        path=path, content=content, revision=hashlib.sha256(raw).hexdigest(), editable=editable
    )


def _current_file(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    *,
    data_dir: Path | None,
    profile_id: str | None,
) -> tuple[Path, bytes, str]:
    _require_writable(category)
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    target = resolve_target(root, path)
    if not target.is_file() or target.is_symlink():
        raise FilePathError("That file was not found.")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise FilePathError("That file could not be read.") from exc
    return target, raw, hashlib.sha256(raw).hexdigest()


def _validate_edit(raw: bytes, content: str) -> tuple[bytes, list[str]]:
    problems: list[str] = []
    if "\x00" in content:
        problems.append("Text content cannot contain null bytes.")
    data = content.encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        problems.append("The edited file is larger than Blockstead can save.")
    return data, problems


def preview_file_edit(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    expected_revision: str,
    content: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> FileEditPreview:
    _target, raw, revision = _current_file(
        server_directory, distribution, category, path, data_dir=data_dir, profile_id=profile_id
    )
    if revision != expected_revision:
        raise FileConflictError("That file changed after it was opened. Reload it and try again.")
    data, problems = _validate_edit(raw, content)
    return FileEditPreview(
        revision=revision, valid=not problems, problems=problems, no_changes=data == raw
    )


def _write_snapshot(
    snapshot_root: Path, profile_id: str, category: FileCategory, name: str, raw: bytes
) -> str:
    snapshot_directory = snapshot_root / "file-snapshots" / profile_id / category
    snapshot_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    snapshot_directory.chmod(0o700)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    snapshot_name = f"{stamp}-{uuid4().hex[:8]}-{name}"
    snapshot = snapshot_directory / snapshot_name
    with snapshot.open("xb") as handle:
        fchmod = getattr(os, "fchmod", None)
        if fchmod is not None:
            fchmod(handle.fileno(), 0o600)
        else:
            snapshot.chmod(0o600)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return snapshot_name


def _replace_atomically(path: Path, raw: bytes, updated: bytes) -> None:
    staging = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with staging.open("xb") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        staging.chmod(path.stat().st_mode & 0o777)
        if path.read_bytes() != raw:
            raise FileConflictError(
                "This file changed while the update was being prepared. Reload and retry."
            )
        os.replace(staging, path)
    except (OSError, FileConflictError):
        staging.unlink(missing_ok=True)
        raise


def apply_file_edit(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    expected_revision: str,
    content: str,
    snapshot_root: Path,
    profile_id: str,
    *,
    data_dir: Path | None = None,
) -> FileEditResult:
    target, raw, revision = _current_file(
        server_directory, distribution, category, path, data_dir=data_dir, profile_id=profile_id
    )
    if revision != expected_revision:
        raise FileConflictError("That file changed after it was opened. Reload it and try again.")
    data, problems = _validate_edit(raw, content)
    if problems:
        raise FilePathError(" ".join(problems))
    if data == raw:
        raise FilePathError("Nothing changed in this file.")
    snapshot_name = _write_snapshot(snapshot_root, profile_id, category, target.name, raw)
    _replace_atomically(target, raw, data)
    return FileEditResult(
        path=path,
        snapshot_name=snapshot_name,
        previous_revision=revision,
        revision=hashlib.sha256(data).hexdigest(),
    )


def rename_file(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    new_name: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> RenameResult:
    _require_writable(category)
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    if _is_protected_world_root(root, path):
        raise FilePathError(
            "World folders can only be replaced through the Backup Center, not renamed here."
        )
    target = resolve_target(root, path)
    if not target.exists() or target.is_symlink():
        raise FilePathError("That item was not found.")
    if (
        not new_name
        or new_name in {".", ".."}
        or "/" in new_name
        or "\\" in new_name
        or "\x00" in new_name
        or new_name.startswith(".")
    ):
        raise FilePathError("That new name is not usable.")
    destination = target.with_name(new_name)
    if destination.exists() or destination.is_symlink():
        raise FilePathError("An item with that name already exists.")
    os.rename(target, destination)
    parent = PurePosixPath(path).parent
    new_path = new_name if str(parent) == "." else (parent / new_name).as_posix()
    return RenameResult(path=new_path)


def delete_file(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    snapshot_root: Path,
    profile_id: str,
    now: datetime,
    *,
    data_dir: Path | None = None,
) -> DeleteResult:
    _require_writable(category)
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    if _is_protected_world_root(root, path):
        raise FilePathError(
            "World folders can only be replaced through the Backup Center, not deleted here."
        )
    target = resolve_target(root, path)
    if not target.exists() or target.is_symlink():
        raise FilePathError("That item was not found.")
    if target.is_dir():
        stamp = now.strftime("pre-delete-%Y%m%d-%H%M%S")
        preserved_name = f"{target.name}.{stamp}"
        os.rename(target, target.with_name(preserved_name))
        return DeleteResult(snapshot_name=None, preserved_name=preserved_name)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise FilePathError("That file could not be read.") from exc
    snapshot_name = _write_snapshot(snapshot_root, profile_id, category, target.name, raw)
    target.unlink()
    return DeleteResult(snapshot_name=snapshot_name, preserved_name=None)


def resolve_upload_target(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    filename: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> Path:
    """Resolve the destination file path for an upload into ``path`` (a
    folder, possibly the category root when empty).

    Uploads never silently overwrite an existing file: rename or delete it
    first, so a delete's own recovery snapshot covers the old content rather
    than every upload needing to copy out whatever it might replace.
    """

    _require_writable(category)
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    relative = f"{path}/{filename}" if path else filename
    target = resolve_target(root, relative)
    if target.exists() or target.is_symlink():
        raise FilePathError(
            "A file with that name already exists. Rename or delete it first."
        )
    return target


def resolve_extract_destination(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> Path:
    _require_writable(category)
    root = _root(server_directory, distribution, category, data_dir=data_dir, profile_id=profile_id)
    if path:
        target = resolve_target(root, path)
        if not target.is_dir() or target.is_symlink():
            raise FilePathError("That destination folder was not found.")
        return target
    if root.allowed_top_level is not None:
        raise FilePathError("Choose a world folder to extract the archive into.")
    return root.base


def extract_archive_into(
    server_directory: Path,
    distribution: str,
    category: FileCategory,
    path: str,
    archive_path: Path,
    now: datetime,
    *,
    data_dir: Path | None = None,
    profile_id: str | None = None,
) -> ArchiveExtractResult:
    destination = resolve_extract_destination(
        server_directory, distribution, category, path, data_dir=data_dir, profile_id=profile_id
    )
    staging = extract_zip_safely(archive_path, destination)
    promoted, preserved = promote_extracted(staging, destination, now)
    return ArchiveExtractResult(promoted=promoted, preserved=preserved)
