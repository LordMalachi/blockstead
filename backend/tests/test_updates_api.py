import asyncio
import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.models import BackupRecord
from blockstead.scheduler import Scheduler
from blockstead.updates import (
    REQUEST_NAME,
    RemoteCommit,
    State,
    read_state,
    request_install,
    write_state,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
OLD_COMMIT = "a" * 40
NEW_COMMIT = "b" * 40
ATTEMPT = "1" * 32


def remote(commit: str = NEW_COMMIT) -> RemoteCommit:
    return RemoteCommit(commit=commit, committed_at=NOW, summary="Add a thing")


def setup_admin(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    return {
        "Origin": "http://testserver",
        "X-CSRF-Token": response.json()["csrf_token"],
    }


def write_stamp(path: Path, commit: str = OLD_COMMIT) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "commit": commit,
                "committed_at": "2026-07-19T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def write_status(
    path: Path,
    state: str,
    *,
    commit: str = NEW_COMMIT,
    rolled_back: bool | None = None,
    attempt: str | None = None,
    retryable: bool = False,
    retry_after: datetime | None = None,
) -> None:
    body: dict[str, object] = {
        "state": state,
        "commit": commit,
        "detail": f"Update {state}.",
        "at": datetime.now(UTC).isoformat(),
        "retryable": retryable,
    }
    if rolled_back is not None:
        body["rolled_back"] = rolled_back
    if attempt is not None:
        body["attempt"] = attempt
    if retry_after is not None:
        body["retry_after"] = retry_after.isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")


def wait_for_manager_state(client: TestClient, expected: str) -> None:
    for _ in range(200):
        if cast(FastAPI, client.app).state.process_manager.snapshot()["state"] == expected:
            return
        time.sleep(0.01)
    raise AssertionError(f"Server did not reach {expected}")


def test_starting_up_does_not_reach_the_network(tmp_path: Path) -> None:
    """A machine that cannot install an update must not poll GitHub for one.

    Development checkouts, the test suite, and Docker all run without the
    privileged helper, so none of them should depend on the network to boot.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
    )
    with patch("blockstead.updates.fetch_latest", new=AsyncMock()) as fetch:
        with TestClient(create_app(settings)):
            pass

    fetch.assert_not_awaited()


def test_the_status_shows_what_is_installed(client: TestClient, auth: dict[str, str]) -> None:
    body = client.get("/api/v1/updates/status").json()

    assert body["build"]["version"] == "0.1.0"
    assert body["decision"] == "current"
    assert body["supported"] is False
    assert body["installing"] is False


def test_the_status_needs_an_administrator(client: TestClient) -> None:
    assert client.get("/api/v1/updates/status").status_code == 401


def test_health_reports_the_exact_installed_commit(tmp_path: Path) -> None:
    stamp = tmp_path / "BUILD"
    write_stamp(stamp)
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        update_build_file=stamp,
    )

    with TestClient(create_app(settings)) as test_client:
        health = test_client.get("/api/v1/health").json()

    assert health["commit"] == OLD_COMMIT
    assert health["short_commit"] == "aaaaaaa"


def test_checking_on_purpose_works_without_the_helper(
    client: TestClient, auth: dict[str, str]
) -> None:
    """Asking deliberately is allowed anywhere, even where installing is not."""
    with patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())):
        body = client.post("/api/v1/updates/check", headers=auth).json()

    assert body["latest"]["commit"] == NEW_COMMIT
    assert body["latest"]["short_commit"] == "bbbbbbb"
    assert body["error"] is None
    # Nothing was stamped here, so the first check adopts what it found rather
    # than reinstalling over a copy that may already be current.
    assert body["decision"] == "current"


def test_github_being_unreachable_is_reported_gently(
    client: TestClient, auth: dict[str, str]
) -> None:
    failing = AsyncMock(side_effect=httpx.ConnectError("no route"))
    with patch("blockstead.updates.fetch_latest", new=failing):
        body = client.post("/api/v1/updates/check", headers=auth).json()

    assert "could not reach GitHub" in str(body["error"])
    assert body["installing"] is False


def test_a_behind_installation_asks_for_the_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: a stamped, behind, idle machine requests the update."""
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
    )
    stamp = tmp_path / "BUILD"
    stamp.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "commit": OLD_COMMIT,
                "committed_at": "2026-07-19T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("blockstead.updates.BUILD_FILE", stamp)
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: True)

    with patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())):
        with TestClient(create_app(settings)) as test_client:
            setup = test_client.post(
                "/api/v1/setup/admin",
                headers={"Origin": "http://testserver"},
                json={"username": "owner", "password": "correct horse battery staple"},
            )
            headers = {
                "Origin": "http://testserver",
                "X-CSRF-Token": setup.json()["csrf_token"],
            }
            body = test_client.post("/api/v1/updates/check", headers=headers).json()

    assert body["decision"] == "install"
    assert body["installing"] is True
    request = data_dir / REQUEST_NAME
    assert request.is_file()
    request_body = json.loads(request.read_text(encoding="utf-8"))
    state = read_state(data_dir)
    assert state.requested_at is not None
    assert request_body["commit"] == NEW_COMMIT
    assert request_body["attempt"] == state.requested_attempt
    assert request_body["requested_at"] == state.requested_at.isoformat()


def test_an_active_helper_is_not_refetched_or_requested_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    status_file = tmp_path / "root-status.json"
    write_status(status_file, "downloading")
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_status_file=status_file,
    )
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: False)
    fetch = AsyncMock(return_value=remote())

    with patch("blockstead.updates.fetch_latest", new=fetch):
        with TestClient(create_app(settings)) as test_client:
            headers = setup_admin(test_client)
            body = test_client.post("/api/v1/updates/check", headers=headers).json()

    fetch.assert_not_awaited()
    assert body["installing"] is True
    assert body["last_result"]["state"] == "downloading"
    assert not (settings.data_dir / REQUEST_NAME).exists()


def test_a_consumed_request_remains_busy_before_its_matching_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    status_file = tmp_path / "root-status.json"
    write_state(
        data_dir,
        State(
            acknowledged_commit=OLD_COMMIT,
            requested_commit=NEW_COMMIT,
            requested_at=datetime.now(UTC),
            requested_attempt=ATTEMPT,
        ),
    )
    write_status(status_file, "succeeded", attempt="2" * 32)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_status_file=status_file,
    )
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: False)
    fetch = AsyncMock(return_value=remote())

    with patch("blockstead.updates.fetch_latest", new=fetch):
        with TestClient(create_app(settings)) as test_client:
            headers = setup_admin(test_client)
            body = test_client.post("/api/v1/updates/check", headers=headers).json()

    fetch.assert_not_awaited()
    assert body["installing"] is True
    assert not (data_dir / REQUEST_NAME).exists()


def test_a_newer_manual_success_clears_installing_and_allows_server_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    status_file = tmp_path / "root-status.json"
    stamp = tmp_path / "BUILD"
    manual_commit = "c" * 40
    write_stamp(stamp, manual_commit)
    requested_at = datetime.now(UTC) - timedelta(seconds=2)
    write_state(
        data_dir,
        State(
            requested_commit=NEW_COMMIT,
            requested_at=requested_at,
            requested_attempt=ATTEMPT,
        ),
    )
    write_status(status_file, "succeeded", commit=manual_commit)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_auto=False,
        update_build_file=stamp,
        update_status_file=status_file,
    )
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: False)

    with TestClient(create_app(settings)) as test_client:
        headers = setup_admin(test_client)
        profile_id = test_client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fixture", "path": str(fixture)},
        ).json()["id"]

        assert test_client.get("/api/v1/updates/status", headers=headers).json()[
            "installing"
        ] is False
        started = test_client.post(
            "/api/v1/server/start",
            headers=headers,
            json={"profile_id": profile_id},
        )
        assert started.status_code == 202
        wait_for_manager_state(test_client, "RUNNING")


def test_an_in_progress_backup_defers_update_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_status_file=tmp_path / "root-status.json",
    )
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: False)
    fetch = AsyncMock(return_value=remote())

    with patch("blockstead.updates.fetch_latest", new=fetch):
        with TestClient(create_app(settings)) as test_client:
            headers = setup_admin(test_client)
            profile_id = test_client.post(
                "/api/v1/profiles",
                headers=headers,
                json={
                    "name": "Fixture",
                    "path": str(
                        Path(__file__).parents[2]
                        / "fixtures"
                        / "servers"
                        / "vanilla-fixture"
                    ),
                },
            ).json()["id"]
            with cast(FastAPI, test_client.app).state.session_factory() as db:
                db.add(BackupRecord(profile_id=profile_id, trigger="manual"))
                db.commit()

            body = test_client.post("/api/v1/updates/check", headers=headers).json()

    fetch.assert_not_awaited()
    assert body["installing"] is False
    assert not (data_dir / REQUEST_NAME).exists()


def test_a_failed_commit_is_suppressed_until_an_administrator_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    stamp = tmp_path / "BUILD"
    status_file = tmp_path / "root-status.json"
    write_stamp(stamp)
    write_status(status_file, "failed", rolled_back=True, attempt=ATTEMPT)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_build_file=stamp,
        update_status_file=status_file,
    )
    capable = {"value": False}
    monkeypatch.setattr(
        "blockstead.updates.update_capable", lambda **_: capable["value"]
    )

    with patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())):
        with TestClient(create_app(settings)) as test_client:
            headers = setup_admin(test_client)
            capable["value"] = True
            checked = test_client.post("/api/v1/updates/check", headers=headers)
            assert checked.json()["decision"] == "failed"
            assert not (data_dir / REQUEST_NAME).exists()

            failed_state = read_state(data_dir)
            write_state(
                data_dir,
                replace(
                    failed_state,
                    requested_commit=NEW_COMMIT,
                    requested_at=datetime.now(UTC) - timedelta(seconds=1),
                    requested_attempt=ATTEMPT,
                    resume_profile_id="profile-that-was-running",
                    resume_commit=NEW_COMMIT,
                ),
            )
            retried = test_client.post("/api/v1/updates/install", headers=headers)

    assert retried.status_code == 200
    assert retried.json()["installing"] is True
    assert (data_dir / REQUEST_NAME).is_file()
    assert read_state(data_dir).resume_profile_id == "profile-that-was-running"


def test_a_failed_request_write_always_releases_the_handoff_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    stamp = tmp_path / "BUILD"
    write_stamp(stamp)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_build_file=stamp,
        update_status_file=tmp_path / "root-status.json",
    )
    capable = {"value": False}
    monkeypatch.setattr(
        "blockstead.updates.update_capable", lambda **_: capable["value"]
    )

    with patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())):
        with TestClient(create_app(settings)) as test_client:
            headers = setup_admin(test_client)
            test_client.post("/api/v1/updates/check", headers=headers)
            capable["value"] = True
            original_write_state = write_state
            writes = 0

            def fail_recovery_write(path: Path, state: State) -> None:
                nonlocal writes
                writes += 1
                if writes == 2:
                    raise OSError("disk unavailable")
                original_write_state(path, state)

            with (
                patch("blockstead.updates.request_install", side_effect=OSError("no space")),
                patch("blockstead.updates.write_state", side_effect=fail_recovery_write),
            ):
                with pytest.raises(OSError, match="no space"):
                    test_client.post("/api/v1/updates/install", headers=headers)

            assert cast(FastAPI, test_client.app).state.update_handoff_active is False


def test_an_empty_running_server_is_remembered_before_automatic_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    stamp = tmp_path / "BUILD"
    write_stamp(stamp)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_build_file=stamp,
        update_status_file=tmp_path / "root-status.json",
    )
    capable = {"value": False}
    monkeypatch.setattr(
        "blockstead.updates.update_capable", lambda **_: capable["value"]
    )
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"

    with TestClient(create_app(settings)) as test_client:
        headers = setup_admin(test_client)
        profile_id = test_client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fixture", "path": str(fixture)},
        ).json()["id"]
        assert (
            test_client.post(
                "/api/v1/server/start", headers=headers, json={"profile_id": profile_id}
            ).status_code
            == 202
        )
        wait_for_manager_state(test_client, "RUNNING")
        capable["value"] = True
        with (
            patch.object(Scheduler, "online_players", new=AsyncMock(return_value=0)),
            patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())),
        ):
            checked = test_client.post("/api/v1/updates/check", headers=headers)

    state = read_state(data_dir)
    assert checked.json()["decision"] == "install"
    assert state.resume_profile_id == profile_id
    assert state.resume_commit == NEW_COMMIT
    assert (data_dir / REQUEST_NAME).is_file()


@pytest.mark.parametrize(
    ("helper_state", "rolled_back", "handed_off"),
    [("succeeded", None, True), ("failed", True, True), (None, None, False)],
)
def test_a_stopped_server_resumes_after_helper_final_or_an_interrupted_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    helper_state: str | None,
    rolled_back: bool | None,
    handed_off: bool,
) -> None:
    data_dir = tmp_path / "data"
    status_file = tmp_path / "root-status.json"
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_auto=False,
        update_status_file=status_file,
        update_status_poll_seconds=0.1,
    )
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    monkeypatch.setattr("blockstead.updates.update_capable", lambda **_: False)

    with TestClient(create_app(settings)) as first:
        headers = setup_admin(first)
        profile_id = first.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fixture", "path": str(fixture)},
        ).json()["id"]

    requested_at = datetime.now(UTC) - timedelta(seconds=1) if handed_off else None
    write_state(
        data_dir,
        State(
            acknowledged_commit=OLD_COMMIT,
            requested_commit=NEW_COMMIT,
            requested_summary="Add a thing",
            requested_at=requested_at,
            requested_attempt=ATTEMPT if handed_off else None,
            resume_profile_id=profile_id,
            resume_commit=NEW_COMMIT,
        ),
    )
    if helper_state is not None:
        write_status(
            status_file,
            helper_state,
            rolled_back=rolled_back,
            attempt=ATTEMPT,
        )

    with TestClient(create_app(settings)) as restarted:
        wait_for_manager_state(restarted, "RUNNING")
        assert cast(FastAPI, restarted.app).state.active_profile_id == profile_id

    assert read_state(data_dir).resume_profile_id is None


def test_server_start_and_restart_are_blocked_during_an_update(
    client: TestClient, auth: dict[str, str]
) -> None:
    request_install(
        cast(FastAPI, client.app).state.settings.data_dir,
        NEW_COMMIT,
        attempt=ATTEMPT,
        requested_at=datetime.now(UTC),
    )

    for endpoint in ("start", "restart"):
        response = client.post(
            f"/api/v1/server/{endpoint}",
            headers=auth,
            json={"profile_id": "profile-1"},
        )
        assert response.status_code == 409
        assert "being updated" in response.json()["error"]["message"]


def test_server_start_is_serialized_before_update_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    stamp = tmp_path / "BUILD"
    write_stamp(stamp)
    settings = Settings(
        data_dir=data_dir,
        server_root=Path(__file__).parents[2] / "fixtures" / "servers",
        allowed_origins="http://testserver",
        update_build_file=stamp,
        update_status_file=tmp_path / "root-status.json",
    )
    capable = {"value": False}
    monkeypatch.setattr(
        "blockstead.updates.update_capable", lambda **_: capable["value"]
    )

    with TestClient(create_app(settings)) as test_client:
        headers = setup_admin(test_client)
        fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
        profile_id = test_client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fixture", "path": str(fixture)},
        ).json()["id"]
        manager = cast(FastAPI, test_client.app).state.process_manager
        original_start = manager.start
        entered, release = threading.Event(), threading.Event()

        async def slow_start(
            arguments: tuple[str, ...] | None = None,
            *,
            cwd: Path | None = None,
            label: str = "Server",
            mode: str = "normal",
            owner: str | None = None,
        ) -> None:
            entered.set()
            await asyncio.to_thread(release.wait)
            await original_start(
                arguments,
                cwd=cwd,
                label=label,
                mode=mode,
                owner=owner,
            )

        monkeypatch.setattr(manager, "start", slow_start)
        responses: dict[str, httpx.Response] = {}
        capable["value"] = True
        with (
            patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())),
            patch.object(Scheduler, "online_players", new=AsyncMock(return_value=1)),
        ):
            start_thread = threading.Thread(
                target=lambda: responses.update(
                    start=test_client.post(
                        "/api/v1/server/start",
                        headers=headers,
                        json={"profile_id": profile_id},
                    )
                )
            )
            start_thread.start()
            assert entered.wait(timeout=2)
            check_thread = threading.Thread(
                target=lambda: responses.update(
                    check=test_client.post("/api/v1/updates/check", headers=headers)
                )
            )
            check_thread.start()
            time.sleep(0.05)
            assert check_thread.is_alive()
            release.set()
            start_thread.join(timeout=3)
            check_thread.join(timeout=3)

        assert responses["start"].status_code == 202
        assert responses["check"].json()["decision"] == "waiting_for_players"
        assert not (data_dir / REQUEST_NAME).exists()


def test_installing_is_refused_where_it_cannot_work(
    client: TestClient, auth: dict[str, str]
) -> None:
    with patch("blockstead.updates.fetch_latest", new=AsyncMock(return_value=remote())):
        client.post("/api/v1/updates/check", headers=auth)
    response = client.post("/api/v1/updates/install", headers=auth)

    assert response.status_code == 409
    assert "cannot update itself" in response.json()["error"]["message"]


def test_acknowledging_clears_the_announcement(
    client: TestClient, auth: dict[str, str], tmp_path: Path
) -> None:
    data_dir = tmp_path / "data"
    write_state(data_dir, State(acknowledged_commit=OLD_COMMIT))

    assert client.get("/api/v1/updates/status").json()["announcement"] is None

    response = client.post("/api/v1/updates/acknowledge", headers=auth)

    assert response.status_code == 200


def test_mutating_endpoints_reject_a_missing_csrf_token(client: TestClient) -> None:
    for path in ("check", "install", "acknowledge"):
        response = client.post(f"/api/v1/updates/{path}", headers={"Origin": "http://testserver"})
        assert response.status_code in {401, 403}, path


def test_a_remote_commit_reports_its_short_form() -> None:
    assert RemoteCommit(commit=NEW_COMMIT, committed_at=NOW, summary="x").short_commit == "bbbbbbb"
