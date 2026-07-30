"""Recognize which Minecraft version a server folder is already running.

A folder brought in from somewhere else carries no Blockstead record, yet nearly
everything downstream needs the version: provisioning a matching loader, judging
extension compatibility, and choosing a Java runtime. Every source consulted here
is a file the server itself wrote, and reading is all that happens. A folder that
cannot be identified reads as unknown rather than as a guess, because a wrong
version silently installs the wrong artifacts later.
"""

import json
import re
import zipfile
from pathlib import Path

#: Matches what the provisioning API accepts, so a detected version can be used
#: wherever an owner-supplied one can.
VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z._-]{0,31}$")

#: Paper records "git-Paper-497 (MC: 1.21.4)" in the folder it manages.
PAPER_VERSION = re.compile(r"\(MC:\s*([0-9][0-9A-Za-z._-]*)\s*\)")

#: Vanilla and Paper both announce this on the first lines of a run.
LOG_VERSION = re.compile(r"[Mm]inecraft server version ([0-9][0-9A-Za-z._-]*)")

#: A launcher jar sits beside the real server jar in loader installs, so more
#: than one candidate is read; the bound keeps a crowded folder cheap to scan.
MAX_JARS = 8
#: Only the opening lines of a log are worth reading; a busy server's latest.log
#: is unbounded, and the version banner is always at the top of a run.
MAX_LOG_LINES = 400


def _valid(value: object) -> str | None:
    if isinstance(value, str) and VERSION_PATTERN.match(value.strip()):
        return value.strip()
    return None


def _from_marker(folder: Path) -> str | None:
    """Read the fixture marker Blockstead's own test servers carry."""
    marker = folder / "fake-server.json"
    try:
        return _valid(json.loads(marker.read_text(encoding="utf-8")).get("minecraft_version"))
    except (OSError, ValueError, AttributeError):
        return None


def _from_jar(path: Path) -> str | None:
    """Read version.json, which Mojang stamps into the server jar itself."""
    try:
        with zipfile.ZipFile(path) as archive, archive.open("version.json") as handle:
            stamped = json.load(handle)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    if not isinstance(stamped, dict):
        return None
    return _valid(stamped.get("id")) or _valid(stamped.get("name"))


def _from_jars(folder: Path) -> str | None:
    try:
        jars = sorted(entry for entry in folder.glob("*.jar") if entry.is_file())
    except OSError:
        return None
    # The plain server jar is the authoritative one when it is present; a
    # loader's launcher jar is only consulted when it is not.
    jars.sort(key=lambda entry: (entry.name != "server.jar", entry.name))
    for jar in jars[:MAX_JARS]:
        found = _from_jar(jar)
        if found:
            return found
    return None


def _from_paper_history(folder: Path) -> str | None:
    try:
        history = json.loads((folder / "version_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(history, dict):
        return None
    current = history.get("currentVersion")
    if not isinstance(current, str):
        return None
    match = PAPER_VERSION.search(current)
    return _valid(match.group(1)) if match else None


def _from_logs(folder: Path) -> str | None:
    log = folder / "logs" / "latest.log"
    try:
        with log.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(MAX_LOG_LINES), handle, strict=False):
                match = LOG_VERSION.search(line)
                if match:
                    return _valid(match.group(1))
    except OSError:
        return None
    return None


def detect_minecraft_version(folder: Path) -> str | None:
    """Identify the Minecraft version of an existing server folder, or None.

    Sources are tried from most to least authoritative. Nothing raises: an
    unreadable, damaged, or unfamiliar folder is simply not identified.
    """
    for source in (_from_marker, _from_jars, _from_paper_history, _from_logs):
        found = source(folder)
        if found:
            return found
    return None
