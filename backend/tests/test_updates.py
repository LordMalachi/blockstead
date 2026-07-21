import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from blockstead.updates import (
    REQUEST_NAME,
    Build,
    Decision,
    HelperStatus,
    RemoteCommit,
    State,
    acknowledge,
    announcement,
    decide,
    failed_commit_suppressed,
    fetch_latest,
    install_in_progress,
    is_behind,
    pending_request,
    read_build,
    read_helper_status,
    read_state,
    request_install,
    retry_delay_seconds,
    status_completes_request,
    update_capable,
    write_state,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
OLD_COMMIT = "a" * 40
NEW_COMMIT = "b" * 40
ATTEMPT = "1" * 32


def manifest(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": 1,
        "repository": "LordMalachi/blockstead",
        "branch": "main",
        "commit": NEW_COMMIT,
        "committed_at": "2026-07-20T12:00:00Z",
        "summary": "Add a thing",
        "published_at": "2026-07-20T12:05:00Z",
    }
    body.update(changes)
    return body


def remote(commit: str = NEW_COMMIT, *, at: datetime = NOW) -> RemoteCommit:
    return RemoteCommit(commit=commit, committed_at=at, summary="Add a thing")


def installed(commit: str | None = OLD_COMMIT, *, at: datetime | None = None) -> Build:
    return Build(
        version="0.1.0",
        commit=commit,
        committed_at=at if at is not None else NOW - timedelta(days=1),
    )


def test_a_build_reads_back_what_the_installer_stamped(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD"
    stamp.write_text(
        json.dumps(
            {
                "version": "0.2.0",
                "commit": OLD_COMMIT,
                "committed_at": "2026-07-19T12:00:00Z",
                "source": "zip",
            }
        ),
        encoding="utf-8",
    )
    build = read_build("0.1.0", build_file=stamp)

    assert build.version == "0.2.0"
    assert build.commit == OLD_COMMIT
    assert build.short_commit == "aaaaaaa"
    assert build.label == "0.2.0 (aaaaaaa)"
    assert build.committed_at == datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_an_unstamped_installation_falls_back_to_the_running_version(tmp_path: Path) -> None:
    build = read_build("0.1.0", build_file=tmp_path / "missing")

    assert build.version == "0.1.0"
    assert build.commit is None
    assert build.label == "0.1.0"


def test_a_damaged_stamp_is_treated_as_no_commit_rather_than_trusted(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD"
    stamp.write_text(json.dumps({"commit": "not-a-commit"}), encoding="utf-8")

    assert read_build("0.1.0", build_file=stamp).commit is None


def test_a_newer_commit_counts_as_behind() -> None:
    assert is_behind(installed(), remote()) is True


def test_the_same_commit_is_not_behind() -> None:
    assert is_behind(installed(NEW_COMMIT), remote()) is False


def test_a_promoted_sha_change_wins_over_unreliable_commit_timestamps() -> None:
    ahead = installed(OLD_COMMIT, at=NOW + timedelta(days=1))

    assert is_behind(ahead, remote()) is True


def test_an_unstamped_installation_compares_against_its_adopted_baseline() -> None:
    unknown = Build(version="0.1.0", commit=None)

    assert is_behind(unknown, remote()) is False
    assert is_behind(unknown, remote(), baseline=OLD_COMMIT) is True
    assert is_behind(unknown, remote(), baseline=NEW_COMMIT) is False


async def test_latest_means_the_promoted_passing_manifest_not_the_live_tip() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=manifest())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        latest = await fetch_latest(
            client,
            "LordMalachi/blockstead",
            "main",
            "https://updates.example/latest.json",
        )

    assert seen["url"] == "https://updates.example/latest.json"
    assert latest == RemoteCommit(
        commit=NEW_COMMIT,
        committed_at=NOW,
        summary="Add a thing",
        published_at=NOW + timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema": 2}, "schema"),
        ({"schema": True}, "schema"),
        ({"repository": "attacker/project"}, "repository"),
        ({"branch": "unreviewed"}, "branch"),
        ({"commit": "b" * 39}, "commit"),
        ({"committed_at": "yesterday"}, "committed_at"),
        ({"committed_at": "2026-07-20T12:00:00"}, "timezone"),
        ({"summary": ""}, "summary"),
        ({"summary": "two\nlines"}, "summary"),
        ({"published_at": None}, "published_at"),
        ({"extra": "not in schema 1"}, "unexpected fields"),
    ],
)
async def test_an_untrusted_update_manifest_is_rejected(
    changes: dict[str, object], message: str
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=manifest(**changes)))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match=message):
            await fetch_latest(
                client,
                "LordMalachi/blockstead",
                "main",
                "https://updates.example/latest.json",
            )


@pytest.mark.parametrize(
    ("running", "players", "expected"),
    [
        (False, None, Decision.INSTALL),
        (True, 0, Decision.STOP_SERVER_FIRST),
        (True, 4, Decision.WAITING_FOR_PLAYERS),
        (True, None, Decision.WAITING_FOR_PLAYERS),
    ],
)
def test_an_update_waits_for_the_server_to_be_free(
    running: bool, players: int | None, expected: Decision
) -> None:
    choice = decide(
        behind=True, auto=True, capable=True, server_running=running, players_online=players
    )

    assert choice is expected


def test_nothing_happens_when_the_installation_is_current() -> None:
    choice = decide(
        behind=False, auto=True, capable=True, server_running=False, players_online=None
    )

    assert choice is Decision.CURRENT


@pytest.mark.parametrize(("auto", "capable"), [(False, True), (True, False), (False, False)])
def test_an_installation_that_cannot_update_itself_says_so(auto: bool, capable: bool) -> None:
    choice = decide(
        behind=True, auto=auto, capable=capable, server_running=False, players_online=None
    )

    assert choice is Decision.MANUAL


def test_a_failed_commit_is_not_selected_again_automatically() -> None:
    choice = decide(
        behind=True,
        auto=True,
        capable=True,
        server_running=False,
        players_online=None,
        failed=True,
    )

    assert choice is Decision.FAILED


def test_state_survives_a_restart(tmp_path: Path) -> None:
    write_state(
        tmp_path,
        State(
            acknowledged_commit=OLD_COMMIT,
            baseline_commit=NEW_COMMIT,
            requested_commit=NEW_COMMIT,
            requested_summary="Add a thing",
            requested_at=NOW,
            requested_attempt=ATTEMPT,
            resume_profile_id="profile-1",
            resume_commit=NEW_COMMIT,
            last_checked_at=NOW,
            last_error=None,
        ),
    )
    restored = read_state(tmp_path)

    assert restored.acknowledged_commit == OLD_COMMIT
    assert restored.baseline_commit == NEW_COMMIT
    assert restored.requested_summary == "Add a thing"
    assert restored.requested_at == NOW
    assert restored.requested_attempt == ATTEMPT
    assert restored.resume_profile_id == "profile-1"
    assert restored.resume_commit == NEW_COMMIT
    assert restored.last_checked_at == NOW


def test_missing_state_reads_as_a_fresh_installation(tmp_path: Path) -> None:
    assert read_state(tmp_path) == State()


def test_requesting_an_install_leaves_only_identity_fields_for_the_helper(tmp_path: Path) -> None:
    request_install(tmp_path, NEW_COMMIT, attempt=ATTEMPT, requested_at=NOW)
    written = json.loads((tmp_path / REQUEST_NAME).read_text(encoding="utf-8"))

    assert written["commit"] == NEW_COMMIT
    assert written["attempt"] == ATTEMPT
    assert written["requested_at"] == NOW.isoformat()
    assert "url" not in written and "repo" not in written
    assert pending_request(tmp_path) == NEW_COMMIT


@pytest.mark.parametrize(
    "commit",
    ["", "short", "../../etc/passwd", "b" * 39, "b" * 41, "B" * 40, f"{'b' * 39};reboot"],
)
def test_anything_that_is_not_a_commit_is_refused(tmp_path: Path, commit: str) -> None:
    """Untrusted request identity is validated before the helper can see it."""
    with pytest.raises(ValueError):
        request_install(tmp_path, commit, attempt=ATTEMPT, requested_at=NOW)

    assert not (tmp_path / REQUEST_NAME).exists()


@pytest.mark.parametrize("attempt", ["", "1" * 31, "1" * 33, "G" * 32, "../" * 11])
def test_anything_that_is_not_an_attempt_id_is_refused(
    tmp_path: Path, attempt: str
) -> None:
    with pytest.raises(ValueError, match="attempt"):
        request_install(tmp_path, NEW_COMMIT, attempt=attempt, requested_at=NOW)

    assert not (tmp_path / REQUEST_NAME).exists()


def test_an_update_request_requires_an_aware_timestamp(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timezone"):
        request_install(
            tmp_path,
            NEW_COMMIT,
            attempt=ATTEMPT,
            requested_at=NOW.replace(tzinfo=None),
        )


def test_atomic_json_replacements_fsync_the_file_and_directory(tmp_path: Path) -> None:
    with patch("blockstead.updates.os.fsync", wraps=os.fsync) as fsync:
        write_state(tmp_path, State(requested_commit=NEW_COMMIT))

    # Every platform flushes the file. POSIX additionally flushes the parent
    # directory to make the atomic rename durable; Windows cannot open a
    # directory with os.open and therefore has no equivalent call here.
    assert fsync.call_count == (2 if os.name == "posix" else 1)


def test_unsupported_directory_fsync_does_not_turn_a_completed_write_into_failure(
    tmp_path: Path,
) -> None:
    real_fsync = os.fsync
    calls = 0

    def fail_directory_fsync(file_descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("directory fsync unsupported")
        real_fsync(file_descriptor)

    with patch("blockstead.updates.os.fsync", side_effect=fail_directory_fsync):
        write_state(tmp_path, State(requested_commit=NEW_COMMIT))

    assert read_state(tmp_path).requested_commit == NEW_COMMIT


def test_no_request_reads_as_nothing_pending(tmp_path: Path) -> None:
    assert pending_request(tmp_path) is None


def write_helper_status(path: Path, **changes: object) -> None:
    body: dict[str, object] = {
        "state": "installing",
        "commit": NEW_COMMIT,
        "detail": "Installing Blockstead bbbbbbb.",
        "at": NOW.isoformat(),
    }
    body.update(changes)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_root_owned_helper_progress_is_read_and_exposed(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    write_helper_status(
        status_file,
        state="failed",
        rolled_back=True,
        retryable=True,
        retry_after=(NOW + timedelta(minutes=30)).isoformat(),
        attempt=ATTEMPT,
    )

    status = read_helper_status(status_file)

    assert status == HelperStatus(
        state="failed",
        commit=NEW_COMMIT,
        detail="Installing Blockstead bbbbbbb.",
        at=NOW,
        rolled_back=True,
        retryable=True,
        retry_after=NOW + timedelta(minutes=30),
        attempt=ATTEMPT,
    )
    assert status.payload()["rolled_back"] is True
    assert status.payload()["attempt"] == ATTEMPT


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "running"},
        {"commit": "not-a-commit"},
        {"detail": ""},
        {"at": "not-a-date"},
        {"rolled_back": "yes"},
        {"retryable": "yes"},
        {"retry_after": "later"},
        {"attempt": "not-an-attempt"},
    ],
)
def test_malformed_helper_status_is_ignored(tmp_path: Path, changes: dict[str, object]) -> None:
    status_file = tmp_path / "status.json"
    write_helper_status(status_file, **changes)

    assert read_helper_status(status_file) is None


def test_a_request_or_fresh_helper_progress_counts_as_installing(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"

    request_install(tmp_path, NEW_COMMIT, attempt=ATTEMPT, requested_at=NOW)
    assert install_in_progress(tmp_path, status_file, now=NOW) is True

    (tmp_path / REQUEST_NAME).unlink()
    write_helper_status(status_file, state="downloading")
    assert install_in_progress(tmp_path, status_file, now=NOW) is True


def test_stale_or_final_helper_status_does_not_count_as_installing(tmp_path: Path) -> None:
    status_file = tmp_path / "status.json"
    write_helper_status(status_file, at=(NOW - timedelta(minutes=61)).isoformat())
    assert install_in_progress(tmp_path, status_file, now=NOW) is False

    write_helper_status(status_file, state="succeeded")
    assert install_in_progress(tmp_path, status_file, now=NOW) is False


def test_consumed_request_stays_busy_until_its_attempt_reaches_a_final_state(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    state = State(
        requested_commit=NEW_COMMIT,
        requested_at=NOW,
        requested_attempt=ATTEMPT,
    )
    write_state(tmp_path, state)

    # The helper has consumed the request but has not replaced an older result.
    write_helper_status(
        status_file,
        state="succeeded",
        attempt="2" * 32,
        at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    assert install_in_progress(tmp_path, status_file, now=NOW) is True

    write_helper_status(
        status_file,
        state="failed",
        at=(NOW - timedelta(seconds=1)).isoformat(),
    )
    assert status_completes_request(state, read_helper_status(status_file)) is False

    write_helper_status(
        status_file,
        state="failed",
        at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    assert status_completes_request(state, read_helper_status(status_file)) is True

    write_helper_status(
        status_file,
        state="failed",
        attempt=ATTEMPT,
        # Matching the random attempt is authoritative even within one second.
        at=NOW.replace(microsecond=0).isoformat(),
    )
    status = read_helper_status(status_file)
    assert status_completes_request(state, status) is True
    assert install_in_progress(tmp_path, status_file, now=NOW) is False


def test_an_abandoned_handoff_stops_counting_as_busy_after_the_timeout(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    write_state(
        tmp_path,
        State(
            requested_commit=NEW_COMMIT,
            requested_at=NOW - timedelta(minutes=61),
            requested_attempt=ATTEMPT,
        ),
    )

    assert install_in_progress(tmp_path, status_file, now=NOW) is False


def test_a_successful_manual_update_supersedes_stale_automatic_handoff_state(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    manual_commit = "c" * 40
    write_state(
        tmp_path,
        State(
            requested_commit=manual_commit,
            requested_at=NOW,
            requested_attempt=ATTEMPT,
        ),
    )
    write_helper_status(
        status_file,
        state="succeeded",
        commit=manual_commit,
        at=(NOW + timedelta(seconds=1)).isoformat(),
    )

    assert (
        install_in_progress(
            tmp_path,
            status_file,
            now=NOW,
            installed_commit=manual_commit,
        )
        is False
    )


def test_a_newer_manual_success_for_the_running_build_supersedes_an_old_handoff(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    manual_commit = "c" * 40
    write_state(
        tmp_path,
        State(
            requested_commit=NEW_COMMIT,
            requested_at=NOW,
            requested_attempt=ATTEMPT,
        ),
    )
    write_helper_status(
        status_file,
        state="succeeded",
        commit=manual_commit,
        at=(NOW + timedelta(seconds=1)).isoformat(),
    )

    assert (
        install_in_progress(
            tmp_path,
            status_file,
            now=NOW,
            installed_commit=manual_commit,
        )
        is False
    )


def test_a_stale_manual_success_cannot_clear_a_newer_automatic_handoff(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    installed_commit = "c" * 40
    write_state(
        tmp_path,
        State(
            requested_commit=NEW_COMMIT,
            requested_at=NOW,
            requested_attempt=ATTEMPT,
        ),
    )
    write_helper_status(
        status_file,
        state="succeeded",
        commit=installed_commit,
        at=(NOW - timedelta(seconds=1)).isoformat(),
    )

    assert (
        install_in_progress(
            tmp_path,
            status_file,
            now=NOW,
            installed_commit=installed_commit,
        )
        is True
    )


def test_a_pending_request_cannot_be_superseded_by_a_manual_success(
    tmp_path: Path,
) -> None:
    status_file = tmp_path / "status.json"
    installed_commit = "c" * 40
    request_install(
        tmp_path,
        NEW_COMMIT,
        attempt=ATTEMPT,
        requested_at=NOW,
    )
    state = State(
        requested_commit=NEW_COMMIT,
        requested_at=NOW,
        requested_attempt=ATTEMPT,
    )
    write_state(tmp_path, state)
    status = HelperStatus(
        "succeeded",
        installed_commit,
        "Manual update completed",
        NOW + timedelta(seconds=1),
    )
    write_helper_status(
        status_file,
        state=status.state,
        commit=status.commit,
        detail=status.detail,
        at=status.at.isoformat(),
    )

    assert (
        status_completes_request(
            state,
            status,
            installed_commit=installed_commit,
            request_pending=True,
        )
        is False
    )
    assert (
        install_in_progress(
            tmp_path,
            status_file,
            now=NOW,
            installed_commit=installed_commit,
        )
        is True
    )


def test_another_automatic_attempt_cannot_supersede_the_persisted_handoff() -> None:
    installed_commit = "c" * 40
    state = State(
        requested_commit=NEW_COMMIT,
        requested_at=NOW,
        requested_attempt=ATTEMPT,
    )
    status = HelperStatus(
        "succeeded",
        installed_commit,
        "Another automatic update completed",
        NOW + timedelta(seconds=1),
        attempt="2" * 32,
    )

    assert (
        status_completes_request(
            state,
            status,
            installed_commit=installed_commit,
            request_pending=False,
        )
        is False
    )


def test_legacy_handoff_uses_a_same_second_timestamp_boundary() -> None:
    state = State(
        requested_commit=NEW_COMMIT,
        requested_at=NOW + timedelta(microseconds=900_000),
    )
    status = HelperStatus("failed", NEW_COMMIT, "Network unavailable", NOW)

    assert status_completes_request(state, status) is True


def test_non_retryable_failure_stays_suppressed_but_a_new_sha_does_not() -> None:
    failed = HelperStatus("failed", NEW_COMMIT, "Bad build", NOW)

    assert failed_commit_suppressed(failed, NEW_COMMIT, now=NOW + timedelta(days=1)) is True
    assert failed_commit_suppressed(failed, "c" * 40, now=NOW) is False


def test_transient_failure_waits_until_its_retry_time() -> None:
    failed = HelperStatus(
        "failed",
        NEW_COMMIT,
        "Network unavailable",
        NOW,
        retryable=True,
        retry_after=NOW + timedelta(minutes=30),
    )

    assert failed_commit_suppressed(failed, NEW_COMMIT, now=NOW) is True
    assert (
        failed_commit_suppressed(failed, NEW_COMMIT, now=NOW + timedelta(minutes=30)) is False
    )
    assert retry_delay_seconds(
        failed,
        now=NOW,
        normal_seconds=6 * 3600,
        minimum_seconds=5 * 60,
    ) == 30 * 60


def test_retry_delay_comes_from_durable_failure_status_without_a_decision() -> None:
    failed = HelperStatus(
        "failed",
        NEW_COMMIT,
        "Network unavailable",
        NOW,
        retryable=True,
        retry_after=NOW - timedelta(minutes=1),
    )

    assert retry_delay_seconds(
        failed,
        now=NOW,
        normal_seconds=6 * 3600,
        minimum_seconds=5 * 60,
    ) == 5 * 60


def test_a_first_run_announces_nothing(tmp_path: Path) -> None:
    assert announcement(installed(), State()) is None


def test_an_installation_the_owner_has_seen_announces_nothing() -> None:
    assert announcement(installed(), State(acknowledged_commit=OLD_COMMIT)) is None


def test_a_completed_update_is_announced_with_what_arrived() -> None:
    build = installed(NEW_COMMIT)
    state = State(
        acknowledged_commit=OLD_COMMIT,
        requested_commit=NEW_COMMIT,
        requested_summary="Add a thing",
    )
    notice = announcement(build, state)

    assert notice is not None
    assert notice["commit"] == NEW_COMMIT
    assert notice["previous_commit"] == OLD_COMMIT
    assert notice["summary"] == "Add a thing"
    assert notice["label"] == "0.1.0 (bbbbbbb)"


def test_a_summary_from_a_different_update_is_not_shown() -> None:
    """Whatever arrived is not necessarily the commit that was asked for."""
    state = State(
        acknowledged_commit=OLD_COMMIT,
        requested_commit="c" * 40,
        requested_summary="Some other change",
    )
    notice = announcement(installed(NEW_COMMIT), state)

    assert notice is not None
    assert notice["summary"] is None


def test_acknowledging_stops_the_announcement_repeating(tmp_path: Path) -> None:
    build = installed(NEW_COMMIT)
    write_state(tmp_path, State(acknowledged_commit=OLD_COMMIT, requested_commit=NEW_COMMIT))

    assert announcement(build, read_state(tmp_path)) is not None

    acknowledge(tmp_path, build)

    assert announcement(build, read_state(tmp_path)) is None


def test_acknowledging_does_not_erase_an_incomplete_resume_attempt(tmp_path: Path) -> None:
    write_state(
        tmp_path,
        State(
            acknowledged_commit=OLD_COMMIT,
            requested_commit=NEW_COMMIT,
            requested_at=NOW,
            requested_attempt=ATTEMPT,
            resume_profile_id="profile-1",
            resume_commit=NEW_COMMIT,
        ),
    )

    acknowledged = acknowledge(tmp_path, installed(NEW_COMMIT))

    assert acknowledged.requested_at == NOW
    assert acknowledged.requested_attempt == ATTEMPT
    assert acknowledged.requested_commit == NEW_COMMIT
    assert acknowledged.resume_profile_id == "profile-1"


def test_a_machine_without_the_helper_cannot_update_itself(tmp_path: Path) -> None:
    assert update_capable(helper=tmp_path / "absent") is False


def test_a_helper_that_is_not_executable_does_not_count(tmp_path: Path) -> None:
    helper = tmp_path / "blockstead-update"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o644)

    assert update_capable(helper=helper) is False


def test_an_executable_helper_makes_self_update_possible(tmp_path: Path) -> None:
    helper = tmp_path / "blockstead-update"
    helper.write_text("#!/bin/sh\n", encoding="utf-8")
    helper.chmod(0o755)

    assert update_capable(helper=helper) is (os.name == "posix")
