import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.models import BackupDestinationCheck, BackupRecord, DiscordPairing, Profile
from blockstead.notification_integrations import (
    WebhookValidationError,
    safe_payload,
    validate_webhook_url,
)


def origin_headers(csrf: str) -> dict[str, str]:
    return {"Origin": "http://testserver", "X-CSRF-Token": csrf}


def login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return origin_headers(response.json()["csrf_token"])


def test_owner_viewer_matrix_and_password_change(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get("/api/v1/auth/me").json() == {"username": "owner", "role": "owner"}
    created = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "helper", "password": "helper password long enough"},
    )
    assert created.status_code == 201, created.text
    account_id = created.json()["id"]

    viewer = login(client, "helper", "helper password long enough")
    assert client.get("/api/v1/auth/me").json() == {"username": "helper", "role": "viewer"}
    assert client.get("/api/v1/profiles", headers=viewer).status_code == 200
    assert client.get("/api/v1/system/diagnostics", headers=viewer).status_code == 403
    assert (
        client.post("/api/v1/server/start", headers=viewer, json={"mode": "normal"}).status_code
        == 403
    )
    changed = client.post(
        "/api/v1/auth/password",
        headers=viewer,
        json={"password": "helper password changed"},
    )
    assert changed.status_code == 200
    assert client.get("/api/v1/auth/me", headers=viewer).status_code == 401

    owner = login(client, "owner", "correct horse battery staple")
    disabled = client.post(
        f"/api/v1/accounts/{account_id}/status",
        headers=owner,
        json={"disabled": True},
    )
    assert disabled.status_code == 200
    assert login_rejected(client, "helper", "helper password changed")


def login_rejected(client: TestClient, username: str, password: str) -> bool:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": username, "password": password},
    )
    return response.status_code == 401


def test_viewer_backup_world_care_owner_routes_are_uniformly_forbidden(
    client: TestClient, auth: dict[str, str]
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Boundary fixture", "path": str(fixture)}
    )
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["id"]
    account = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "helper", "password": "helper password long enough"},
    )
    assert account.status_code == 201, account.text
    viewer = login(client, "helper", "helper password long enough")
    backup_id = "guessed-backup-id"
    plan_id = "guessed-cleanup-plan"
    routes: list[tuple[str, str, dict[str, object] | None]] = [
        ("GET", f"/api/v1/profiles/{profile_id}/backups/{backup_id}/download", None),
        ("POST", f"/api/v1/profiles/{profile_id}/backups", None),
        ("GET", f"/api/v1/profiles/{profile_id}/backup-policy", None),
        (
            "PUT",
            f"/api/v1/profiles/{profile_id}/backup-policy",
            {
                "keep_count": 10,
                "keep_days": None,
                "max_total_mb": None,
                "redundancy_enabled": False,
                "destinations": [],
            },
        ),
        ("GET", f"/api/v1/profiles/{profile_id}/backups/{backup_id}/restore-preview", None),
        ("POST", f"/api/v1/profiles/{profile_id}/backups/{backup_id}/restore", None),
        (
            "POST",
            f"/api/v1/profiles/{profile_id}/backups/{backup_id}/recovery-drill",
            None,
        ),
        ("GET", f"/api/v1/profiles/{profile_id}/world-care/cleanup-plan", None),
        (
            "POST",
            f"/api/v1/profiles/{profile_id}/world-care/cleanup-plan/{plan_id}/apply",
            {"confirm": True},
        ),
        ("POST", f"/api/v1/profiles/{profile_id}/backup-destinations/check", None),
    ]
    for method, path, body in routes:
        response = client.request(method, path, headers=viewer, json=body)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["error"]["code"] == "REQUEST_FORBIDDEN"


def test_viewer_backup_and_world_care_payloads_redact_nested_private_evidence(
    client: TestClient, auth: dict[str, str]
) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Redaction fixture", "path": str(fixture)}
    )
    assert profile.status_code == 201, profile.text
    profile_id = profile.json()["id"]
    factory = client.app.state.session_factory
    created_at = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    with factory() as db:
        record = BackupRecord(
            profile_id=profile_id,
            status="completed",
            method="world_archive",
            trigger="manual",
            file_name="/private/secret-world.tar.gz",
            manifest_name="/private/secret-world.json",
            sha256="f" * 64,
            included_paths=json.dumps(["/private/world"]),
            size_bytes=4096,
            duration_ms=125,
            result="Protected /private/world in secret-world.tar.gz",
            created_at=created_at,
            completed_at=created_at,
        )
        db.add(record)
        profile_row = db.get(Profile, profile_id)
        assert profile_row is not None
        profile_row.backup_destinations = json.dumps(["/private/mirror-drive"])
        db.add(
            BackupDestinationCheck(
                profile_id=profile_id,
                destination_path="/private/mirror-drive",
                label="Approved backup destination",
                state="available",
                write_verified=True,
                read_verified=True,
                detail="Checked /private/mirror-drive/secret-probe",
                checked_at=created_at,
            )
        )
        db.commit()

    history_owner = client.get(f"/api/v1/profiles/{profile_id}/backups", headers=auth)
    assert history_owner.status_code == 200
    owner_record = history_owner.json()[0]
    account = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "helper", "password": "helper password long enough"},
    )
    assert account.status_code == 201, account.text
    viewer = login(client, "helper", "helper password long enough")

    history = client.get(f"/api/v1/profiles/{profile_id}/backups", headers=viewer)
    assert history.status_code == 200, history.text
    viewer_record = history.json()[0]
    assert set(viewer_record) == {
        "id",
        "profile_id",
        "status",
        "method",
        "trigger",
        "size_bytes",
        "duration_ms",
        "result",
        "created_at",
        "completed_at",
    }
    assert viewer_record["result"] == "Backup completed successfully."
    assert viewer_record["result"] != owner_record["result"]
    assert all(
        value not in history.text
        for value in ("secret-world.tar.gz", "/private/world", "f" * 64, "/private/mirror-drive")
    )

    world_care = client.get(f"/api/v1/profiles/{profile_id}/world-care", headers=viewer)
    assert world_care.status_code == 200, world_care.text
    payload = world_care.json()
    assert payload["disk"]["path"] == ""
    assert payload["last_verified_backup"]["result"] == "Backup completed successfully."
    assert payload["last_verified_backup"]["file_name"] is None
    assert payload["last_verified_backup"]["archive_available"] is False
    assert payload["last_verified_backup"]["sha256"] is None
    assert payload["last_verified_backup"]["included_paths"] == []
    for destination_payload in payload["backup_destinations"]:
        assert destination_payload["configured_path"] == ""
        assert destination_payload["disk"]["path"] == ""
        if destination_payload["last_check"]:
            assert destination_payload["last_check"]["detail"] == (
                "A private destination check completed."
            )
    assert "/private" not in world_care.text
    assert "secret-world.tar.gz" not in world_care.text
    assert "f" * 64 not in world_care.text


def test_one_time_recovery_token_expires_after_reuse(
    client: TestClient, auth: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "helper", "password": "helper password long enough"},
    )
    account_id = created.json()["id"]
    recovery = client.post(f"/api/v1/accounts/{account_id}/recovery", headers=auth)
    assert recovery.status_code == 200
    token = recovery.json()["token"]
    redeemed = client.post(
        "/api/v1/auth/password-recovery",
        headers={"Origin": "http://testserver"},
        json={"token": token, "password": "recovered password long"},
    )
    assert redeemed.status_code == 200
    reused = client.post(
        "/api/v1/auth/password-recovery",
        headers={"Origin": "http://testserver"},
        json={"token": token, "password": "another password long"},
    )
    assert reused.status_code == 400
    assert login_rejected(client, "helper", "helper password long enough")
    assert login(client, "helper", "recovered password long")["X-CSRF-Token"]


def test_webhook_validation_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "blockstead.notification_integrations.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))],
    )
    assert validate_webhook_url("https://discord.com/api/webhooks/123/secret")
    for value in (
        "http://discord.com/api/webhooks/123/secret",
        "https://discord.com/api/webhooks/123/secret?token=raw",
    ):
        with pytest.raises(WebhookValidationError):
            validate_webhook_url(value)
    monkeypatch.setattr(
        "blockstead.notification_integrations.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    with pytest.raises(WebhookValidationError, match="non-public"):
        validate_webhook_url("https://discord.com/api/webhooks/123/secret")
    result = safe_payload(
        {
            "title": "Crash",
            "severity": "danger",
            "detail": "secret=abc /srv/minecraft/world from 192.168.1.5",
            "created_at": "now",
            "recovery_to": "/activity",
        }
    )
    assert "abc" not in result["detail"]
    assert "192.168.1.5" not in result["detail"]
    assert "/srv/minecraft" not in result["detail"]


def test_discord_integration_is_masked_and_owner_only(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "blockstead.app.validate_webhook_url",
        lambda value: value.strip(),
    )
    created = client.post(
        "/api/v1/notification-integrations",
        headers=auth,
        json={"webhook_url": "https://discord.com/api/webhooks/123/secret"},
    )
    assert created.status_code == 201, created.text
    assert "secret" not in created.text
    assert "••••" in created.json()["webhook_display"]
    viewer = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "helper", "password": "helper password long enough"},
    )
    viewer_headers = login(client, "helper", "helper password long enough")
    assert (
        client.get("/api/v1/notification-integrations", headers=viewer_headers).status_code
        == 403
    )
    assert viewer.status_code == 201


def test_discord_pairing_requires_confirmation_and_masks_code(
    client: TestClient, auth: dict[str, str]
) -> None:
    client.app.state.settings.discord_application_id = "1535816544951476324"
    client.app.state.settings.discord_relay_url = "https://relay.test"
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    created = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Discord fixture", "path": str(fixture)},
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]

    class RelayStub:
        def register_pairing(
            self, requested_profile_id: str, profile_name: str, code: str
        ) -> dict[str, object]:
            assert requested_profile_id == profile_id
            return {"id": "relay-pairing-1"}

        def confirm_pairing(self, pairing_id: str) -> dict[str, object]:
            assert pairing_id == "relay-pairing-1"
            return {
                "protocol_version": 1,
                "id": "relay-connection-1",
                "connection_id": "relay-connection-1",
                "installation_id": (
                    client.app.state.settings.discord_relay_installation_id
                ),
                "profile_id": profile_id,
                "application_id": "1535816544951476324",
                "guild_id": "900000000000000002",
                "channel_id": "900000000000000003",
                "share_address": False,
                "publish_address": False,
            }

        def update_connection(
            self, connection_id: str, **changes: object
        ) -> dict[str, object]:
            assert connection_id == "relay-connection-1"
            return changes

    client.app.state.relay_client = RelayStub()

    pairing = client.post(
        "/api/v1/discord/pairings",
        headers=auth,
        json={"profile_id": profile_id},
    )
    assert pairing.status_code == 201, pairing.text
    code = pairing.json()["code"]
    assert code not in pairing.json()["id"]

    factory = client.app.state.session_factory
    with factory() as db:
        record = db.get(DiscordPairing, pairing.json()["id"])
        assert record is not None
        assert code not in record.code_hash
        record.claimed_application_id = "1535816544951476324"
        record.claimed_guild_id = "900000000000000002"
        record.claimed_channel_id = "900000000000000003"
        record.claimed_user_id = "900000000000000004"
        record.claimed_role_ids = json.dumps(["900000000000000005"])
        record.claimed_at = datetime.now(UTC)
        db.commit()

    confirmed = client.post(
        f"/api/v1/discord/pairings/{pairing.json()['id']}/confirm",
        headers=auth,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["profile_id"] == profile_id
    assert confirmed.json()["publish_address"] is False
    assert confirmed.json()["authorized_user_ids"] == ["900000000000000004"]
    assert confirmed.json()["authorized_role_ids"] == []

    status = client.get("/api/v1/discord/status", headers=auth)
    assert status.status_code == 200, status.text
    assert status.json()["legacy_token_present"] is False
    assert status.json()["relay_online"] is False
    assert status.json()["discord_online"] is False
    assert status.json()["bot_ready"] is False
    assert status.json()["connections"][0]["guild_id"] == "900000000000000002"

    changed = client.post(
        f"/api/v1/discord/connections/{confirmed.json()['id']}/status",
        headers=auth,
        json={"share_address": True, "publish_address": True},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["publish_address"] is True
    assert changed.json()["share_address"] is True

    principals = client.post(
        f"/api/v1/discord/connections/{confirmed.json()['id']}/status",
        headers=auth,
        json={
            "authorized_user_ids": [
                "900000000000000004",
                "900000000000000006",
                "900000000000000006",
            ],
            "authorized_role_ids": ["900000000000000007"],
        },
    )
    assert principals.status_code == 200, principals.text
    assert principals.json()["authorized_user_ids"] == [
        "900000000000000004",
        "900000000000000006",
    ]
    assert principals.json()["authorized_role_ids"] == ["900000000000000007"]

    owner_removal = client.post(
        f"/api/v1/discord/connections/{confirmed.json()['id']}/status",
        headers=auth,
        json={"authorized_user_ids": ["900000000000000006"]},
    )
    assert owner_removal.status_code == 422
    client.app.state.relay_client = None


def test_saved_setup_variant_uses_isolated_copy_and_preserves_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "servers"
    root.mkdir()
    settings = Settings(data_dir=tmp_path / "data", server_root=root, allowed_origins="http://testserver")
    source = root / "source"
    source.mkdir()
    (source / "server.properties").write_text("level-name=world\n", encoding="utf-8")
    (source / "server.jar").write_bytes(b"launcher")
    (source / "fake-server.json").write_text('{"minecraft_version":"1.21.1"}\n', encoding="utf-8")
    (source / "world").mkdir()
    (source / "world" / "level.dat").write_bytes(b"original")

    async def fake_resolve(*_args: object, **_kwargs: object):
        from blockstead.provisioning import ProvisionPlan

        return ProvisionPlan(
            distribution="vanilla",
            minecraft_version="1.21.1",
            loader_version=None,
            file_name="server.jar",
            url="https://example.test/server.jar",
            checksum_algorithm="sha256",
            checksum="a" * 64,
            notes=[],
        )

    async def fake_provision(
        _client: object, server_root: Path, directory_name: str, *_args: object, **_kwargs: object
    ):
        from blockstead.provisioning import ProvisionResult

        target = server_root / directory_name
        target.mkdir()
        (target / "server.jar").write_bytes(b"launcher")
        return ProvisionResult(plan=await fake_resolve(), directory=str(target), sha256="b" * 64)

    monkeypatch.setattr("blockstead.app.resolve_plan", fake_resolve)
    monkeypatch.setattr("blockstead.app.provision_profile", fake_provision)
    monkeypatch.setattr("blockstead.app.required_java_major", lambda _version: None)
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v1/setup/admin",
            headers={"Origin": "http://testserver"},
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        headers = origin_headers(setup.json()["csrf_token"])
        profile = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Source", "path": str(source)},
        )
        profile_id = profile.json()["id"]
        backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=headers)
        setup_group = client.post(
            "/api/v1/saved-setups",
            headers=headers,
            json={"name": "Snapshots", "profile_id": profile_id},
        )
        setup_id = setup_group.json()["id"]
        review = client.post(
            f"/api/v1/saved-setups/{setup_id}/variants/review",
            headers=headers,
            json={
                "source_profile_id": profile_id,
                "name": "Copy",
                "directory_name": "copy",
                "target_distribution": "vanilla",
            },
        )
        assert review.status_code == 200, review.text
        body = review.json()
        applied = client.post(
            f"/api/v1/saved-setups/{setup_id}/variants",
            headers=headers,
            json={
                "source_profile_id": profile_id,
                "name": "Copy",
                "directory_name": "copy",
                "target_distribution": "vanilla",
                "loader_version": body["loader_version"],
                "review_id": body["review_id"],
                "backup_id": backup.json()["id"],
                "acknowledge_modded_world": False,
            },
        )
        assert applied.status_code == 201, applied.text
        assert (source / "world" / "level.dat").read_bytes() == b"original"
        assert (root / "copy" / "world" / "level.dat").read_bytes() == b"original"
        assert applied.json()["source_unchanged"] is True
