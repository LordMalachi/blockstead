"""Keep Blockstead current without the owner downloading anything by hand.

Blockstead follows the newest *passing* commit on the ``main`` branch of its
GitHub repository. A GitHub Actions workflow promotes that commit by publishing
a small manifest only after the test suite succeeds. Every commit carries the
same release version, so the version string alone cannot say whether an
installation is behind; the commit itself is the identity, and the version is
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
from datetime import datetime, timedelta, timezone
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

DEFAULT_MANIFEST_URL = (
    "https://github.com/LordMalachi/blockstead/releases/download/update-channel/latest.json"
)
MANIFEST_SCHEMA = 1

HELPER_STATES = frozenset({"downloading", "installing", "succeeded", "failed"})
HELPER_ACTIVE_STATES = frozenset({"downloading", "installing"})
HELPER_FINAL_STATES = frozenset({"succeeded", "failed"})

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ATTEMPT_PATTERN = re.compile(r"^[0-9a-f]{32}$")

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
    #: This exact commit already failed and will not be retried automatically.
    FAILED = "failed"


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
    """The newest passing commit on the branch Blockstead follows."""

    commit: str
    committed_at: datetime
    summary: str
    published_at: datetime | None = None

    @property
    def short_commit(self) -> str:
        return self.commit[:7]

    def payload(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "short_commit": self.short_commit,
            "committed_at": self.committed_at.isoformat(),
            "summary": self.summary,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


@dataclass(frozen=True)
class HelperStatus:
    """Durable progress written by the root-owned update helper."""

    state: str
    commit: str
    detail: str
    at: datetime
    rolled_back: bool | None = None
    retryable: bool = False
    retry_after: datetime | None = None
    attempt: str | None = None

    @property
    def active(self) -> bool:
        return self.state in HELPER_ACTIVE_STATES

    @property
    def final(self) -> bool:
        return self.state in HELPER_FINAL_STATES

    def fresh(
        self, *, now: datetime | None = None, max_age: timedelta = timedelta(minutes=60)
    ) -> bool:
        """Whether an active status is recent enough to describe live work."""
        current = now or datetime.now(timezone.utc)  # noqa: UP017
        age = current - self.at
        # A little forward clock skew is harmless; a wildly future-dated status
        # must not suppress updates forever.
        return -timedelta(minutes=5) <= age <= max_age

    def payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "state": self.state,
            "commit": self.commit,
            "detail": self.detail,
            "at": self.at.isoformat(),
            "retryable": self.retryable,
            "retry_after": self.retry_after.isoformat() if self.retry_after else None,
        }
        if self.rolled_back is not None:
            payload["rolled_back"] = self.rolled_back
        if self.attempt is not None:
            payload["attempt"] = self.attempt
        return payload


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
    requested_at: datetime | None = None
    requested_attempt: str | None = None
    #: An empty server stopped specifically for an update is brought back after
    #: the helper reaches a final state, including after a failed attempt rolls
    #: the previous application back.
    resume_profile_id: str | None = None
    resume_commit: str | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "acknowledged_commit": self.acknowledged_commit,
            "baseline_commit": self.baseline_commit,
            "requested_commit": self.requested_commit,
            "requested_summary": self.requested_summary,
            "requested_at": self.requested_at.isoformat() if self.requested_at else None,
            "requested_attempt": self.requested_attempt,
            "resume_profile_id": self.resume_profile_id,
            "resume_commit": self.resume_commit,
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
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # Directory fsync makes rename ordering durable on Linux. Some
            # supported development platforms/filesystems do not permit it;
            # the successfully replaced file remains valid there.
            log.debug("Directory fsync is unavailable for %s", path.parent)
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

    requested_attempt = text("requested_attempt")
    if requested_attempt is not None and not ATTEMPT_PATTERN.fullmatch(requested_attempt):
        requested_attempt = None

    return State(
        acknowledged_commit=text("acknowledged_commit"),
        baseline_commit=text("baseline_commit"),
        requested_commit=text("requested_commit"),
        requested_summary=text("requested_summary"),
        requested_at=_parse_moment(raw.get("requested_at")),
        requested_attempt=requested_attempt,
        resume_profile_id=text("resume_profile_id"),
        resume_commit=text("resume_commit"),
        last_checked_at=_parse_moment(raw.get("last_checked_at")),
        last_error=text("last_error"),
    )


def write_state(data_dir: Path, state: State) -> None:
    _write_json(data_dir / STATE_NAME, state.payload())


def update_capable(*, helper: Path | None = None) -> bool:
    """Can this installation actually install an update on its own?"""
    target = helper if helper is not None else UPDATE_HELPER
    return target.is_file() and os.access(target, os.X_OK)


def _required_manifest_moment(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"The update manifest has no usable {field}.")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"The update manifest has no usable {field}.") from exc
    if moment.tzinfo is None:
        raise ValueError(f"The update manifest {field} must include a timezone.")
    return moment


async def fetch_latest(
    client: httpx.AsyncClient,
    repository: str,
    branch: str = "main",
    manifest_url: str = DEFAULT_MANIFEST_URL,
) -> RemoteCommit:
    """Read and authenticate the promoted latest-passing-main manifest.

    The repository and branch in the document must exactly match local policy.
    This prevents either the unprivileged application or a malformed channel
    document from redirecting the root helper to unrelated code.
    """
    response = await client.get(manifest_url, headers={"Accept": "application/json"})
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("The update manifest was not a JSON object.")
    expected_fields = {
        "schema",
        "repository",
        "branch",
        "commit",
        "committed_at",
        "summary",
        "published_at",
    }
    if set(body) != expected_fields:
        raise ValueError("The update manifest contained unexpected fields.")
    if type(body.get("schema")) is not int or body["schema"] != MANIFEST_SCHEMA:
        raise ValueError("The update manifest uses an unsupported schema.")
    if body.get("repository") != repository:
        raise ValueError("The update manifest named an unexpected repository.")
    if body.get("branch") != branch:
        raise ValueError("The update manifest named an unexpected branch.")
    commit = body.get("commit")
    if not isinstance(commit, str) or not COMMIT_PATTERN.match(commit):
        raise ValueError("The update manifest did not name a usable commit.")
    summary = body.get("summary")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or summary != summary.strip()
        or "\n" in summary
        or "\r" in summary
        or len(summary) > 500
    ):
        raise ValueError("The update manifest did not contain a usable summary.")
    return RemoteCommit(
        commit=commit,
        committed_at=_required_manifest_moment(body.get("committed_at"), "committed_at"),
        summary=summary,
        published_at=_required_manifest_moment(body.get("published_at"), "published_at"),
    )


def is_behind(build: Build, remote: RemoteCommit, *, baseline: str | None = None) -> bool:
    """Whether the installed build differs from the promoted channel build.

    Git timestamps are not an ordering primitive: successive commits can share
    a second and a contributor's clock can run behind. The post-CI manifest is
    the authority, so a different promoted SHA is the update signal.
    """
    known = build.commit or baseline
    if known is None:
        return False
    return known != remote.commit


def decide(
    *,
    behind: bool,
    auto: bool,
    capable: bool,
    server_running: bool,
    players_online: int | None,
    failed: bool = False,
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
    if failed:
        return Decision.FAILED
    if not server_running:
        return Decision.INSTALL
    if players_online is None or players_online > 0:
        return Decision.WAITING_FOR_PLAYERS
    return Decision.STOP_SERVER_FIRST


def request_install(
    data_dir: Path, commit: str, *, attempt: str, requested_at: datetime
) -> None:
    """Ask the privileged helper to install a commit.

    Only build identity and an opaque correlation ID travel. The helper holds
    its own repository address and ignores anything else here, so this file
    cannot redirect an update even if the service account were taken over.
    """
    if not COMMIT_PATTERN.match(commit):
        raise ValueError("That is not a commit Blockstead can install.")
    if not ATTEMPT_PATTERN.fullmatch(attempt):
        raise ValueError("That is not a usable Blockstead update attempt.")
    if requested_at.tzinfo is None:
        raise ValueError("An update request timestamp must include a timezone.")
    _write_json(
        data_dir / REQUEST_NAME,
        {
            "commit": commit,
            "attempt": attempt,
            "requested_at": requested_at.isoformat(),
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


def read_helper_status(status_file: Path) -> HelperStatus | None:
    """Read a status file that only the privileged helper may write."""
    raw = _read_json(status_file)
    state = raw.get("state")
    commit = raw.get("commit")
    detail = raw.get("detail")
    at = _parse_moment(raw.get("at"))
    if (
        not isinstance(state, str)
        or state not in HELPER_STATES
        or not isinstance(commit, str)
        or not COMMIT_PATTERN.match(commit)
        or not isinstance(detail, str)
        or not detail
        or len(detail) > 2000
        or at is None
    ):
        return None
    rolled_back = raw.get("rolled_back")
    if rolled_back is not None and not isinstance(rolled_back, bool):
        return None
    retryable = raw.get("retryable", False)
    if not isinstance(retryable, bool):
        return None
    retry_after_raw = raw.get("retry_after")
    retry_after = _parse_moment(retry_after_raw)
    if retry_after_raw is not None and retry_after is None:
        return None
    attempt = raw.get("attempt")
    if attempt is not None and (
        not isinstance(attempt, str) or not ATTEMPT_PATTERN.fullmatch(attempt)
    ):
        return None
    return HelperStatus(
        state=state,
        commit=commit,
        detail=detail,
        at=at,
        rolled_back=rolled_back,
        retryable=retryable,
        retry_after=retry_after,
        attempt=attempt,
    )


def status_completes_request(
    state: State,
    status: HelperStatus | None,
    *,
    installed_commit: str | None = None,
    request_pending: bool | None = None,
) -> bool:
    """Whether a final helper note belongs to the persisted handoff.

    New requests carry a random attempt identifier so rapid retries of the same
    SHA cannot be confused. A manual update can supersede an older handoff, but
    only after its request has disappeared and its success is newer than that
    handoff. The timestamp fallback also finishes updates that crossed the
    upgrade from the older status contract. Callers that have not inspected the
    request file leave ``request_pending`` unknown, which conservatively
    disables manual supersession.
    """
    if request_pending is True:
        return False
    requested_commit = state.requested_commit or state.resume_commit
    if (
        status is not None
        and status.final
        and status.attempt is None
        and status.state == "succeeded"
        and installed_commit is not None
        and request_pending is False
        and state.requested_at is not None
        and status.commit == installed_commit
        and status.at >= state.requested_at
    ):
        # A manual updater owns the same OS lock as the automatic helper. Once
        # no request remains, a newer success matching the BUILD that is
        # actually running proves it superseded the persisted handoff, even if
        # that handoff named a different commit. Automatic attempts still need
        # their exact opaque ID below.
        return True
    if (
        status is None
        or not status.final
        or requested_commit is None
        or status.commit != requested_commit
    ):
        return False
    if state.requested_attempt is not None:
        if status.attempt is not None:
            return status.attempt == state.requested_attempt
        # A legacy/manual helper cannot echo the random ID. It may still finish
        # a handoff, but only a final note strictly after the precise request
        # boundary qualifies; an older same-SHA result remains non-authoritative.
        return state.requested_at is not None and status.at >= state.requested_at
    if state.requested_at is None:
        return False
    legacy_boundary = state.requested_at.replace(microsecond=0)
    return status.at >= legacy_boundary


def install_in_progress(
    data_dir: Path,
    status_file: Path,
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(minutes=60),
    installed_commit: str | None = None,
) -> bool:
    """Whether an update is queued, handed off, or reporting live work."""
    request_pending = pending_request(data_dir) is not None
    if request_pending:
        return True
    status = read_helper_status(status_file)
    if status and status.active and status.fresh(now=now, max_age=max_age):
        return True
    state = read_state(data_dir)
    if state.requested_at is None or state.requested_commit is None:
        return False
    if status_completes_request(
        state,
        status,
        installed_commit=installed_commit,
        request_pending=request_pending,
    ):
        return False
    current = now or datetime.now(timezone.utc)  # noqa: UP017
    age = current - state.requested_at
    return -timedelta(minutes=5) <= age <= max_age


def failed_commit_suppressed(
    status: HelperStatus | None, commit: str, *, now: datetime | None = None
) -> bool:
    """Whether automatic installation should leave a failed commit alone.

    Bad builds remain suppressed until the channel moves or an administrator
    explicitly retries. A transient failure may opt into a bounded retry by
    providing both ``retryable`` and ``retry_after``.
    """
    if status is None or status.state != "failed" or status.commit != commit:
        return False
    if not status.retryable or status.retry_after is None:
        return True
    current = now or datetime.now(timezone.utc)  # noqa: UP017
    return current < status.retry_after


def retry_delay_seconds(
    status: HelperStatus | None,
    *,
    now: datetime,
    normal_seconds: float,
    minimum_seconds: float,
) -> float | None:
    """Return the next transient retry delay directly from durable status."""
    if (
        status is None
        or status.state != "failed"
        or not status.retryable
        or status.retry_after is None
    ):
        return None
    remaining = (status.retry_after - now).total_seconds()
    return max(minimum_seconds, min(normal_seconds, remaining))


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
        requested_commit=state.requested_commit if state.resume_profile_id else None,
        requested_summary=state.requested_summary if state.resume_profile_id else None,
        # The helper may still be finishing after the new dashboard becomes
        # healthy. Keep the attempt boundary until the stopped server has been
        # resumed, so an old same-SHA status cannot satisfy that recovery work.
        requested_at=state.requested_at if state.resume_profile_id else None,
        requested_attempt=state.requested_attempt if state.resume_profile_id else None,
        resume_profile_id=state.resume_profile_id,
        resume_commit=state.resume_commit,
        last_checked_at=state.last_checked_at,
        last_error=state.last_error,
    )
    write_state(data_dir, updated)
    return updated
