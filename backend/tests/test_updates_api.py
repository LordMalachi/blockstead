import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.updates import REQUEST_NAME, RemoteCommit, State, write_state

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
OLD_COMMIT = "a" * 40
NEW_COMMIT = "b" * 40


def remote(commit: str = NEW_COMMIT) -> RemoteCommit:
    return RemoteCommit(commit=commit, committed_at=NOW, summary="Add a thing")


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
    import httpx

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
    assert NEW_COMMIT in request.read_text(encoding="utf-8")


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
