from fastapi.testclient import TestClient


def test_health_reveals_no_server_details(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.json() == {"status": "ok"}
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
