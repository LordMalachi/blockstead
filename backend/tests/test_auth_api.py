from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from blockstead.cli import reset_administrator_password
from blockstead.models import Administrator, LoginSession
from blockstead.security import SESSION_COOKIE, digest

ORIGIN = {"Origin": "http://testserver"}
PASSWORD = "correct horse battery staple"  # noqa: S105 - deliberately fake test credential
NEW_PASSWORD = "an entirely new password"  # noqa: S105 - deliberately fake test credential


def test_health_reveals_no_server_details(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "commit": None,
        "short_commit": None,
    }
    assert response.headers["x-frame-options"] == "DENY"


def test_first_admin_is_single_use_and_password_is_not_returned(client: TestClient) -> None:
    payload = {"username": "owner", "password": "correct horse battery staple"}
    created = client.post(
        "/api/v1/setup/admin", headers={"Origin": "http://testserver"}, json=payload
    )
    assert created.status_code == 201
    assert payload["password"] not in created.text
    duplicate = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "other", "password": payload["password"]},
    )
    assert duplicate.status_code == 409


def test_mutation_rejects_missing_auth_and_csrf(client: TestClient, auth: dict[str, str]) -> None:
    with TestClient(client.app) as anonymous:
        assert (
            anonymous.post(
                "/api/v1/server/start", headers={"Origin": "http://testserver"}, json={}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/server/start", headers={"Origin": "http://testserver"}, json={}
        ).status_code
        == 403
    )
    wrong = {**auth, "Origin": "https://evil.example"}
    assert client.post("/api/v1/server/start", headers=wrong, json={}).status_code == 403


def test_production_errors_are_structured(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "missing", "password": "correct horse battery staple"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert "traceback" not in response.text.lower()


def test_login_accepts_trimmed_case_insensitive_username(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "  HomeOwner  ", "password": PASSWORD},
    )
    assert created.status_code == 201
    assert created.json()["username"] == "HomeOwner"
    client.cookies.clear()

    login = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": "  homeowner  ", "password": PASSWORD},
    )

    assert login.status_code == 200
    assert login.json()["username"] == "HomeOwner"


def test_correct_password_clears_failed_login_throttle(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    ).status_code == 201
    client.cookies.clear()

    for _ in range(5):
        failed = client.post(
            "/api/v1/auth/login",
            headers=ORIGIN,
            json={"username": "owner", "password": "definitely the wrong password"},
        )
        assert failed.status_code == 401
    limited = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": "owner", "password": "definitely the wrong password"},
    )
    assert limited.status_code == 429

    accepted = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    )
    assert accepted.status_code == 200


def test_reset_password_works_immediately_while_login_is_throttled(
    client: TestClient,
) -> None:
    assert client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    ).status_code == 201
    client.cookies.clear()
    for _ in range(5):
        assert client.post(
            "/api/v1/auth/login",
            headers=ORIGIN,
            json={"username": "owner", "password": "definitely the wrong password"},
        ).status_code == 401

    database = client.app.state.settings.data_dir / "blockstead.db"
    reset_administrator_password(database, NEW_PASSWORD)
    accepted = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": "owner", "password": NEW_PASSWORD},
    )

    assert accepted.status_code == 200


def test_damaged_password_hash_gives_recovery_guidance(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    ).status_code == 201
    client.cookies.clear()
    factory = client.app.state.session_factory
    with factory.begin() as db:
        administrator = db.scalar(select(Administrator))
        assert administrator is not None
        administrator.password_hash = "not-an-argon2-hash"  # noqa: S105

    response = client.post(
        "/api/v1/auth/login",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    )

    assert response.status_code == 500
    assert "password recovery command" in response.json()["error"]["message"]
    assert "not-an-argon2-hash" not in response.text


def test_expired_session_is_removed_when_it_is_used(client: TestClient) -> None:
    created = client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    )
    assert created.status_code == 201
    factory = client.app.state.session_factory
    with factory.begin() as db:
        administrator = db.scalar(select(Administrator))
        assert administrator is not None
        db.add(
            LoginSession(
                admin_id=administrator.id,
                token_hash=digest("expired browser token"),
                csrf_hash=digest("expired csrf token"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),  # noqa: UP017
            )
        )
    client.cookies.set(SESSION_COOKIE, "expired browser token")

    assert client.get("/api/v1/auth/me").status_code == 401
    with factory() as db:
        remaining = db.scalar(
            select(func.count()).select_from(LoginSession).where(
                LoginSession.token_hash == digest("expired browser token")
            )
        )
    assert remaining == 0


def test_password_reset_closes_an_authenticated_log_socket(client: TestClient) -> None:
    assert client.post(
        "/api/v1/setup/admin",
        headers=ORIGIN,
        json={"username": "owner", "password": PASSWORD},
    ).status_code == 201
    client.app.state.websocket_auth_recheck_seconds = 0.01

    with client.websocket_connect("/api/v1/server/logs/ws", headers=ORIGIN) as websocket:
        database = client.app.state.settings.data_dir / "blockstead.db"
        reset_administrator_password(database, NEW_PASSWORD)
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert closed.value.code == 1008
