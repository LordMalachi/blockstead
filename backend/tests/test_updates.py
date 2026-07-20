import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from blockstead.updates import (
    REQUEST_NAME,
    Build,
    Decision,
    RemoteCommit,
    State,
    acknowledge,
    announcement,
    decide,
    is_behind,
    pending_request,
    read_build,
    read_state,
    request_install,
    update_capable,
    write_state,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
OLD_COMMIT = "a" * 40
NEW_COMMIT = "b" * 40


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


def test_an_older_published_commit_never_replaces_newer_installed_code() -> None:
    """A rewritten branch must not push a machine backwards."""
    ahead = installed(OLD_COMMIT, at=NOW + timedelta(days=1))

    assert is_behind(ahead, remote()) is False


def test_an_unstamped_installation_compares_against_its_adopted_baseline() -> None:
    unknown = Build(version="0.1.0", commit=None)

    assert is_behind(unknown, remote()) is False
    assert is_behind(unknown, remote(), baseline=OLD_COMMIT) is True
    assert is_behind(unknown, remote(), baseline=NEW_COMMIT) is False


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


def test_state_survives_a_restart(tmp_path: Path) -> None:
    write_state(
        tmp_path,
        State(
            acknowledged_commit=OLD_COMMIT,
            baseline_commit=NEW_COMMIT,
            requested_commit=NEW_COMMIT,
            requested_summary="Add a thing",
            last_checked_at=NOW,
            last_error=None,
        ),
    )
    restored = read_state(tmp_path)

    assert restored.acknowledged_commit == OLD_COMMIT
    assert restored.baseline_commit == NEW_COMMIT
    assert restored.requested_summary == "Add a thing"
    assert restored.last_checked_at == NOW


def test_missing_state_reads_as_a_fresh_installation(tmp_path: Path) -> None:
    assert read_state(tmp_path) == State()


def test_requesting_an_install_leaves_only_the_commit_for_the_helper(tmp_path: Path) -> None:
    request_install(tmp_path, NEW_COMMIT)
    written = json.loads((tmp_path / REQUEST_NAME).read_text(encoding="utf-8"))

    assert written["commit"] == NEW_COMMIT
    assert "url" not in written and "repo" not in written
    assert pending_request(tmp_path) == NEW_COMMIT


@pytest.mark.parametrize(
    "commit",
    ["", "short", "../../etc/passwd", "b" * 39, "b" * 41, "B" * 40, f"{'b' * 39};reboot"],
)
def test_anything_that_is_not_a_commit_is_refused(tmp_path: Path, commit: str) -> None:
    """The commit is the only value crossing into the privileged helper."""
    with pytest.raises(ValueError):
        request_install(tmp_path, commit)

    assert not (tmp_path / REQUEST_NAME).exists()


def test_no_request_reads_as_nothing_pending(tmp_path: Path) -> None:
    assert pending_request(tmp_path) is None


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

    assert update_capable(helper=helper) is True
