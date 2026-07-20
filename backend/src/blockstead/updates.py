"""Keep Blockstead current without the owner downloading anything by hand.

Blockstead follows the ``main`` branch of its GitHub repository. Every commit
carries the same release version, so the version string alone cannot say whether
an installation is behind; the commit itself is the identity, and the version is
kept only as the label an owner recognises.

The application runs as an unprivileged service that cannot write ``/opt`` and
cannot use ``sudo`` — the systemd unit sets ``NoNewPrivileges`` and mounts the
system read-only apart from a few owner-data paths. So the application never
performs an update itself. It writes a small request file into its own data
directory, and a root-owned systemd path unit notices the file and runs the
privileged helper. That indirection also keeps the update alive: installing
stops the Blockstead service, which would otherwise kill the very process that
started the work.

Nothing here reaches out to the Minecraft server or the database. The decision
about *when* it is polite to update is expressed by :func:`decide`, which takes
plain values so the policy can be read and tested on its own.
"""

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import httpx

#: Where the installer places the application and stamps what it installed.
APP_DIR = Path("/opt/blockstead")
BUILD_FILE = APP_DIR / "BUILD"
#: The privileged helper. Its presence is what makes self-update possible; a
#: development checkout or a Docker image has no helper and only ever checks.
UPDATE_HELPER = Path("/usr/lib/blockstead/blockstead-update")

REQUEST_NAME = "update-request.json"
STATE_NAME = "update-state.json"
RESULT_NAME = "update-result.json"

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

log = logging.getLogger(__name__)


class Decision(str, Enum):
    """What the application should do about an update it has found."""

    #: Nothing newer exists.
    CURRENT = "current"
    #: Newer code exists and it is safe to install right now.
    INSTALL = "install"
    #: Newer code exists and the empty Minecraft server should be stopped first.
    STOP_SERVER_FIRST = "stop_server_first"
    #: Newer code exists but people are playing, so it waits.
    WAITING_FOR_PLAYERS = "waiting_for_players"
    #: Newer code exists but this installation cannot update itself.
    MANUAL = "manual"


@dataclass(frozen=True)
class Build:
    """What is installed right now."""

    version: str
    commit: str | None = None
    committed_at: datetime | None = None
    source: str = "unknown"

    @property
    def short_commit(self) -> str | None:
        return self.commit[:7] if self.commit else None

    @property
    def label(self) -> str:
        """How this build is named to an owner, e.g. ``0.1.0 (a1b2c3d)``."""
        return f"{self.version} ({self.short_commit})" if self.commit else self.version

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "commit": self.commit,
            "short_commit": self.short_commit,
            "committed_at": self.committed_at.isoformat() if self.committed_at else None,
            "label": self.label,
            "source": self.source,
        }


@dataclass(frozen=True)
class RemoteCommit:
    """The newest commit on the branch Blockstead follows."""

    commit: str
    committed_at: datetime
    summary: str

    @property
    def short_commit(self) -> str:
        return self.commit[:7]

    def payload(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "short_commit": self.short_commit,
            "committed_at": self.committed_at.isoformat(),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class State:
    """What the application remembers about updating between restarts."""

    #: The build the owner has already been told about. ``None`` on a brand new
    #: installation, which is how a first run avoids announcing itself.
    acknowledged_commit: str | None = None
    #: Adopted the first time a check succeeds on an installation whose own
    #: commit was never stamped, so an unknown build does not reinstall itself.
    baseline_commit: str | None = None
    #: The commit handed to the privileged helper, kept with its summary so the
    #: announcement after the restart can say what arrived.
    requested_commit: str | None = None
    requested_summary: str | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "acknowledged_commit": self.acknowledged_commit,
            "baseline_commit": self.baseline_commit,
            "requested_commit": self.requested_commit,
            "requested_summary": self.requested_summary,
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else None,
            "last_error": self.last_error,
        }


def _parse_moment(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)  # noqa: UP017


def _read_json(path: Path) -> dict[str, object]:
    try:
        with path.open(encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    """Replace a file in one step so a reader never sees it half written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, path)
    except OSError:
        Path(handle.name).unlink(missing_ok=True)
        raise


def read_build(version: str, *, build_file: Path | None = None) -> Build:
    """Read what the installer stamped, falling back to the running version."""
    raw = _read_json(build_file if build_file is not None else BUILD_FILE)
    commit = raw.get("commit")
    if not isinstance(commit, str) or not COMMIT_PATTERN.match(commit):
        commit = None
    stamped = raw.get("version")
    return Build(
        version=stamped if isinstance(stamped, str) and stamped else version,
        commit=commit,
        committed_at=_parse_moment(raw.get("committed_at")),
        source=str(raw.get("source") or "unknown"),
    )


def read_state(data_dir: Path) -> State:
    raw = _read_json(data_dir / STATE_NAME)

    def text(key: str) -> str | None:
        value = raw.get(key)
        return value if isinstance(value, str) and value else None

    return State(
        acknowledged_commit=text("acknowledged_commit"),
        baseline_commit=text("baseline_commit"),
        requested_commit=text("requested_commit"),
        requested_summary=text("requested_summary"),
        last_checked_at=_parse_moment(raw.get("last_checked_at")),
        last_error=text("last_error"),
    )


def write_state(data_dir: Path, state: State) -> None:
    _write_json(data_dir / STATE_NAME, state.payload())


def update_capable(*, helper: Path | None = None) -> bool:
    """Can this installation actually install an update on its own?"""
    target = helper if helper is not None else UPDATE_HELPER
    return target.is_file() and os.access(target, os.X_OK)


async def fetch_latest(
    client: httpx.AsyncClient, repo: str, branch: str = "main"
) -> RemoteCommit:
    """Ask GitHub for the newest commit on the branch Blockstead follows."""
    response = await client.get(
        f"https://api.github.com/repos/{repo}/commits/{branch}",
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    body = response.json()
    commit = body.get("sha")
    if not isinstance(commit, str) or not COMMIT_PATTERN.match(commit):
        raise ValueError("GitHub did not return a usable commit for that branch.")
    details = body.get("commit") or {}
    committed_at = _parse_moment((details.get("committer") or {}).get("date"))
    if committed_at is None:
        raise ValueError("GitHub did not say when that commit was made.")
    message = details.get("message")
    summary = message.splitlines()[0].strip() if isinstance(message, str) and message else ""
    return RemoteCommit(commit=commit, committed_at=committed_at, summary=summary)


def is_behind(build: Build, remote: RemoteCommit, *, baseline: str | None = None) -> bool:
    """Is the installed build older than what the branch now holds?

    The commit date has to move forward as well as the commit changing. That
    keeps a rewritten branch, or a development checkout that is ahead of the
    published branch, from installing older code over newer code.
    """
    known = build.commit or baseline
    if known is None:
        return False
    if known == remote.commit:
        return False
    if build.committed_at is not None and remote.committed_at <= build.committed_at:
        return False
    return True


def decide(
    *,
    behind: bool,
    auto: bool,
    capable: bool,
    server_running: bool,
    players_online: int | None,
) -> Decision:
    """Decide whether it is a polite moment to install.

    The installer refuses to run while the Blockstead service still has a child
    process, and a running Minecraft server is exactly that. So a running server
    is stopped first when it is empty, and an update waits when it is not. An
    unknown player count is treated as "someone might be playing", which is the
    same conservative choice scheduled maintenance makes.
    """
    if not behind:
        return Decision.CURRENT
    if not capable or not auto:
        return Decision.MANUAL
    if not server_running:
        return Decision.INSTALL
    if players_online is None or players_online > 0:
        return Decision.WAITING_FOR_PLAYERS
    return Decision.STOP_SERVER_FIRST


def request_install(data_dir: Path, commit: str) -> None:
    """Ask the privileged helper to install a commit.

    Only the commit travels. The helper holds its own copy of the repository
    address and ignores anything else here, so this file cannot redirect an
    update somewhere else even if the service account were taken over.
    """
    if not COMMIT_PATTERN.match(commit):
        raise ValueError("That is not a commit Blockstead can install.")
    _write_json(
        data_dir / REQUEST_NAME,
        {
            "commit": commit,
            "requested_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        },
    )
    log.info("Requested Blockstead update to commit %s", commit[:7])


def pending_request(data_dir: Path) -> str | None:
    """The commit an update is already running for, if one is."""
    commit = _read_json(data_dir / REQUEST_NAME).get("commit")
    return commit if isinstance(commit, str) and COMMIT_PATTERN.match(commit) else None


def read_result(data_dir: Path) -> dict[str, object] | None:
    """What the privileged helper reported about the last attempt."""
    result = _read_json(data_dir / RESULT_NAME)
    return result or None


def announcement(build: Build, state: State) -> dict[str, object] | None:
    """The "you are now on a newer Blockstead" notice, when one is due.

    A brand new installation has nothing acknowledged yet and is seeded quietly
    by :func:`acknowledge`, so the notice only ever follows a real update.
    """
    if state.acknowledged_commit is None or build.commit is None:
        return None
    if state.acknowledged_commit == build.commit:
        return None
    return {
        "version": build.version,
        "label": build.label,
        "commit": build.commit,
        "short_commit": build.short_commit,
        "previous_commit": state.acknowledged_commit,
        "summary": state.requested_summary if state.requested_commit == build.commit else None,
    }


def acknowledge(data_dir: Path, build: Build) -> State:
    """Record that the owner has seen the build that is running."""
    state = read_state(data_dir)
    updated = State(
        acknowledged_commit=build.commit or state.acknowledged_commit,
        baseline_commit=state.baseline_commit,
        requested_commit=None,
        requested_summary=None,
        last_checked_at=state.last_checked_at,
        last_error=state.last_error,
    )
    write_state(data_dir, updated)
    return updated
