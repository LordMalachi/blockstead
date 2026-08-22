"""Host filesystem safety helpers shared by every write path in Blockstead.

Blockstead writes into directories the user owns on their own machine, so
almost every failure here is a permissions problem, a read-only mount, a
missing parent folder, a full disk, or a file a running Minecraft server
still has open — not a bug in the write itself. This module centralizes the
platform-aware pieces so every writer in the codebase handles them the same
way instead of re-inventing (and sometimes getting wrong) its own idiom:

- ``restrict_to_owner`` / ``copy_mode`` / ``apply_mode`` — POSIX permission
  bits. **Never call ``Path.chmod`` or ``os.chmod`` directly** outside this
  module. POSIX mode bits do not translate to Windows ACLs at all: there,
  ``chmod`` only toggles the read-only attribute, so ``chmod(0o700)`` on a
  directory restricts nothing. Calling it unguarded is worse than useless —
  it reads like access hardening while providing none, and a read-only mode
  would instead set an attribute that breaks later writes and ``rmtree``.
  Every helper here is therefore an explicit, documented no-op on Windows,
  so the platform assumption is stated once and audited in one place rather
  than implied at a dozen call sites. See ``docs/host-filesystem-notes.md``.
- ``atomic_write_bytes`` / ``atomic_write_text`` — stage in the destination
  directory, fsync, then ``os.replace`` so a crash mid-write leaves the old
  content intact, never a truncated file.
- ``remove_readonly`` / ``rmtree`` — a ``shutil.rmtree`` that clears the
  Windows read-only attribute on a file before retrying instead of failing
  outright (imported Minecraft folders can legitimately contain read-only
  files, especially after being copied from Windows media), and that raises
  on failure instead of silently ignoring it, so a rollback that did not
  actually roll back cannot look like success.
- ``describe_os_error`` — turn a raw ``OSError`` into a plain-English
  diagnostic naming the path, the constraint, and what the user should do,
  never an errno or a Windows error code.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

#: Windows sharing-violation WinError codes raised when another process
#: (typically a running Minecraft server) still has the file open.
_WINDOWS_SHARING_VIOLATION_CODES = frozenset({32, 33})


def apply_mode(path: Path, mode: int) -> None:
    """Set POSIX permission bits on ``path``; a documented no-op on Windows.

    Every other permission helper in this module is built on this one
    function so there is exactly one platform check to audit. See the
    module docstring for why Windows never receives a raw chmod here.
    """
    if sys.platform == "win32":
        return
    path.chmod(mode & 0o777)


def restrict_to_owner(path: Path, *, fd: int | None = None) -> None:
    """Best-effort: keep a file or directory private to its owning account.

    POSIX: applies mode ``0o700`` to a directory or ``0o600`` to a file. When
    ``fd`` is given (an open descriptor for a just-created file), ``fchmod``
    is used instead of a path-based chmod so the mode change cannot race a
    rename of the path out from under it; this replaces the
    ``getattr(os, "fchmod", None)`` dance previously duplicated at several
    call sites.

    Windows: no-op. A per-user Blockstead install already has directories
    that inherit an ACL private to the owning account; skipping the chmod
    here is what keeps that access intact. See the module docstring.
    """
    if sys.platform == "win32":
        return
    fchmod = getattr(os, "fchmod", None)
    if fd is not None and fchmod is not None:
        fchmod(fd, 0o600)
        return
    apply_mode(path, 0o700 if path.is_dir() else 0o600)


def copy_mode(source: Path, target: Path) -> None:
    """Preserve ``source``'s POSIX permission bits on ``target``.

    This is mode *preservation* for a staged replace (a service account may
    run under a deliberately narrowed umask, and the replacement should not
    silently loosen or tighten that), not hardening — unlike
    ``restrict_to_owner`` it does not force a fixed mode. No-op on Windows
    for the same ACL-safety reason.
    """
    apply_mode(target, source.stat().st_mode)


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    before_replace: Callable[[Path], None] | None = None,
) -> None:
    """Write ``data`` to ``path`` without ever leaving a truncated file.

    The content is written to a temporary file in the same directory (so the
    final ``os.replace`` is same-filesystem and atomic), flushed and
    ``fsync``ed, then swapped into place. A crash or power loss at any point
    before the replace leaves the previous content of ``path`` untouched;
    the temporary file is removed on any failure.

    ``before_replace``, if given, runs on the staged temp file just before
    the replace — typically ``restrict_to_owner`` or a ``copy_mode`` partial,
    so the file has its final permissions before it ever appears under its
    real name.

    Raises whatever ``OSError`` the write or the replace produces —
    including a plain ``PermissionError`` on Windows when the destination is
    still held open by a running process. Callers should catch ``OSError``
    and use :func:`describe_os_error` to build a message rather than
    surfacing the raw error to a user.
    """
    directory = path.parent
    fd, temp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    staging = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if before_replace is not None:
            before_replace(staging)
        os.replace(staging, path)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise


def atomic_write_text(
    path: Path,
    text: str,
    *,
    encoding: str = "utf-8",
    before_replace: Callable[[Path], None] | None = None,
) -> None:
    """Text-mode wrapper around :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode(encoding), before_replace=before_replace)


def fsync_path(path: Path) -> None:
    """``fsync`` an existing file's contents by path.

    For writers that cannot go through :func:`atomic_write_bytes` because
    they stream their own output (``tarfile``, ``zipfile``, a chunked
    download), call this on the staged file before the final
    ``os.replace`` so a crash cannot leave a durably-renamed but truncated
    file. The descriptor is opened read/write rather than read-only:
    ``fsync`` on a read-only descriptor fails on Windows.
    """
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def remove_readonly(function: Callable[..., object], path: str, error: BaseException) -> None:
    """``shutil.rmtree`` ``onexc`` handler: retry after clearing a read-only bit.

    Imported Minecraft folders can legitimately contain read-only files,
    especially after being copied from Windows media. Any other failure —
    including anything involving a symlink — is re-raised unchanged.
    """
    if not isinstance(error, PermissionError):
        raise error
    target = Path(path)
    if sys.platform != "win32" or target.is_symlink():
        raise error
    target.chmod(target.stat().st_mode | stat.S_IWRITE)
    function(path)


def rmtree(path: Path) -> None:
    """Remove a directory tree, clearing Windows read-only files as needed.

    Unlike ``shutil.rmtree(path, ignore_errors=True)`` — which appears
    throughout this codebase's history and silently turns a failed rollback
    into an apparent success — this raises ``OSError`` on failure. Callers
    performing genuinely best-effort temporary cleanup (where the operation
    already succeeded or its failure is already being reported some other
    way) should catch ``OSError`` explicitly and say why they are ignoring
    it, rather than defaulting to ``ignore_errors=True``.
    """
    shutil.rmtree(path, onexc=remove_readonly)


def describe_os_error(exc: OSError, path: Path) -> str:
    """Translate a raw ``OSError`` into a plain-English diagnostic for ``path``.

    Names the path, the constraint, and what the user should do next — never
    an errno number or a raw Windows error code. Household users are not
    expected to know what ``EROFS`` or ``WinError 32`` mean.
    """
    display = str(path)
    winerror = getattr(exc, "winerror", None)
    if isinstance(exc, PermissionError) and winerror in _WINDOWS_SHARING_VIOLATION_CODES:
        return (
            f"{display} is still open by a running Minecraft server. "
            "Stop the server, then try again."
        )
    if isinstance(exc, PermissionError):
        return (
            f"Blockstead does not have permission to write to {display}. "
            "Check that this folder belongs to the account running Blockstead "
            "and is not on a read-only or network location, then try again."
        )
    if isinstance(exc, FileNotFoundError) or exc.errno == errno.ENOENT:
        return f"{display} was not found. Check that its folder was not moved or deleted."
    if exc.errno == errno.EROFS:
        return f"{display} is on a read-only disk and cannot be changed."
    if exc.errno == errno.ENOSPC:
        return f"There is not enough free disk space to write {display}."
    detail = exc.strerror or str(exc)
    return f"{display} could not be written to: {detail}."
