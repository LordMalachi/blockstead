import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.discord_relay import (
    RelayError,
    ensure_relay_identity,
    load_relay_identity_state,
)
from blockstead.models import (
    Administrator,
    AuditEvent,
    DiscordCommandAudit,
    DiscordConnection,
    DiscordPairing,
    Profile,
)

APPLICATION_ID = "1535816544951476324"
GUILD_ID = "900000000000000002"
CHANNEL_ID = "900000000000000003"
OWNER_ID = "900000000000000004"
ROLE_ID = "900000000000000005"
EVENT_TIME = "2026-08-21T12:00:00+00:00"


def _seed_connection(client: TestClient, auth: dict[str, str]) -> tuple[str, str]:
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    response = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Discord event fixture", "path": str(fixture)},
    )
    assert response.status_code == 201, response.text
    profile_id = response.json()["id"]
    factory = client.app.state.session_factory
    with factory() as db:
        owner = db.scalar(select(Administrator).where(Administrator.username == "owner"))
        assert owner is not None
        connection = DiscordConnection(
            admin_id=owner.id,
            profile_id=profile_id,
            relay_connection_id="relay-connection-1",
            application_id=APPLICATION_ID,
            guild_id=GUILD_ID,
            channel_id=CHANNEL_ID,
            owner_user_id=OWNER_ID,
            authorized_user_ids=json.dumps([OWNER_ID]),
            authorized_role_ids="[]",
        )
        db.add(connection)
        db.commit()
        return profile_id, connection.id


def _dispatch(client: TestClient, event: dict[str, object]) -> None:
    client.portal.call(client.app.state.relay_event, event)


def _command_event(client: TestClient, event_id: str = "audit-event-1") -> dict[str, object]:
    return {
        "type": "command_audit",
        "protocol_version": 1,
        "id": event_id,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": "profile-id",
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "user_id": OWNER_ID,
        "command": "status",
        "result": "accepted",
        "outcome": "accepted",
        "safe_detail": "Command accepted.",
        "created_at": EVENT_TIME,
        "timestamp": EVENT_TIME,
        "options": {"secret": "must-not-be-stored"},
    }


def test_command_audit_is_binding_scoped_idempotent_and_redacted(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event = _command_event(client)
    event["profile_id"] = profile_id
    event["connection_id"] = "relay-connection-1"

    _dispatch(client, event)
    _dispatch(client, {**event, "options": {"secret": "duplicate-secret"}})

    with client.app.state.session_factory() as db:
        audits = db.scalars(select(DiscordCommandAudit)).all()
        assert len(audits) == 1
        assert audits[0].connection_id == connection_id
        assert audits[0].safe_detail == "Command accepted."
        assert "secret" not in audits[0].safe_detail


@pytest.mark.parametrize(
    ("field", "mismatch"),
    [
        ("installation_id", "other-installation"),
        ("connection_id", "other-connection"),
        ("profile_id", "other-profile"),
        ("application_id", "other-application"),
        ("guild_id", "other-guild"),
        ("channel_id", "other-channel"),
    ],
)
def test_command_audit_rejects_every_binding_mismatch_and_missing_field(
    client: TestClient,
    auth: dict[str, str],
    field: str,
    mismatch: str,
) -> None:
    profile_id, _ = _seed_connection(client, auth)
    event = _command_event(client, f"audit-{field}")
    event["profile_id"] = profile_id
    event[field] = mismatch
    _dispatch(client, event)
    missing = _command_event(client, f"audit-{field}-missing")
    missing["profile_id"] = profile_id
    missing.pop(field)
    _dispatch(client, missing)

    with client.app.state.session_factory() as db:
        assert db.scalars(select(DiscordCommandAudit)).all() == []


def test_command_audit_ignores_missing_or_invalid_evidence_time(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, _ = _seed_connection(client, auth)
    for index, field, value in (
        (1, "created_at", None),
        (2, "timestamp", "not-a-timestamp"),
        (3, "created_at", "2026-08-21T12:00:00"),
    ):
        event = _command_event(client, f"audit-time-{index}")
        event["profile_id"] = profile_id
        event[field] = value
        _dispatch(client, event)

    with client.app.state.session_factory() as db:
        assert db.scalars(select(DiscordCommandAudit)).all() == []


def test_delivery_event_persists_only_safe_binding_and_delivery_state(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_delivery",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "status_message_id": ROLE_ID,
        "result": "delivered",
        "outcome": "delivered",
        "detail": "Status message delivered.",
        "delivered_at": EVENT_TIME,
        "timestamp": EVENT_TIME,
        "detail_payload": "token=do-not-store",
    }
    _dispatch(client, event)

    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.status_message_id == ROLE_ID
        assert connection.last_delivery_result == "delivered"
        assert connection.last_delivery_at == datetime.fromisoformat(EVENT_TIME).replace(
            tzinfo=None
        )
        assert connection.last_delivery_detail == "Status message delivered."

    unsafe = {**event, "detail": "secret=token", "timestamp": EVENT_TIME}
    _dispatch(client, unsafe)
    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.last_delivery_detail == "Status message delivered."


def test_relay_heartbeat_requires_the_exact_binding_and_receipt_time(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_heartbeat",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "received_at": EVENT_TIME,
    }
    _dispatch(client, event)

    expected = datetime.fromisoformat(EVENT_TIME).replace(tzinfo=None)
    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.last_relay_heartbeat_at == expected

    _dispatch(client, {**event, "profile_id": "wrong-profile"})
    _dispatch(client, {**event, "received_at": "2026-08-23T12:00:00"})
    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.last_relay_heartbeat_at == expected


def test_delivery_event_accepts_only_safe_retrying_evidence(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_delivery",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "status_message_id": ROLE_ID,
        "result": "retrying",
        "outcome": "retrying",
        "detail": "Status message delivery is retrying.",
        "delivered_at": EVENT_TIME,
        "timestamp": EVENT_TIME,
        "detail_payload": "token=must-not-be-stored",
    }

    _dispatch(client, event)

    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.status_message_id is None
        assert connection.last_delivery_result == "retrying"
        assert connection.last_delivery_detail == "Status message delivery is retrying."
        assert "token" not in connection.last_delivery_detail


@pytest.mark.parametrize(
    "field",
    ["installation_id", "connection_id", "profile_id", "application_id", "guild_id", "channel_id"],
)
def test_delivery_event_rejects_missing_or_mismatched_binding(
    client: TestClient, auth: dict[str, str], field: str
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_delivery",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "result": "delivered",
        "outcome": "delivered",
        "detail": "Status message delivered.",
        "delivered_at": EVENT_TIME,
        "timestamp": EVENT_TIME,
    }
    event[field] = "mismatch"
    _dispatch(client, event)
    event.pop(field)
    _dispatch(client, event)

    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.last_delivery_result is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delivered_at", None),
        ("timestamp", None),
        ("delivered_at", "not-a-timestamp"),
        ("timestamp", "not-a-timestamp"),
        ("delivered_at", "2026-08-21T12:00:00"),
        ("timestamp", "2026-08-21T12:00:00"),
    ],
)
def test_delivery_event_rejects_missing_invalid_or_naive_timestamps(
    client: TestClient,
    auth: dict[str, str],
    field: str,
    value: object,
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_delivery",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "status_message_id": ROLE_ID,
        "result": "delivered",
        "outcome": "delivered",
        "detail": "Status message delivered.",
        "delivered_at": EVENT_TIME,
        "timestamp": EVENT_TIME,
    }
    if value is None:
        event.pop(field)
    else:
        event[field] = value
    _dispatch(client, event)

    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        assert connection.status_message_id is None
        assert connection.last_delivery_result is None
        assert connection.last_delivery_at is None
        assert connection.last_delivery_detail is None


def test_orphan_activation_is_revoked_without_cross_binding(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, _ = _seed_connection(client, auth)
    # An unrelated relay id must never attach to a local connection based only
    # on the human-readable profile/guild/channel tuple.
    with client.app.state.session_factory() as db:
        connection = db.scalar(
            select(DiscordConnection).where(DiscordConnection.profile_id == profile_id)
        )
        assert connection is not None
        connection.relay_connection_id = None
        db.commit()

    class ConnectorStub:
        connected = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        async def send_profile_binding_unavailable(
            self,
            connection_id: str,
            profile_id: str,
            *,
            application_id: str,
            guild_id: str,
            channel_id: str,
            reason: str,
        ) -> None:
            assert (application_id, guild_id, channel_id) == (
                APPLICATION_ID,
                GUILD_ID,
                CHANNEL_ID,
            )
            self.calls.append((connection_id, profile_id, reason))

    connector = ConnectorStub()
    client.app.state.relay_connector = connector
    _dispatch(
        client,
        {
            "type": "connection_activated",
            "protocol_version": 1,
            "installation_id": client.app.state.settings.discord_relay_installation_id,
            "id": "orphan-relay-connection",
            "connection_id": "orphan-relay-connection",
            "profile_id": "missing-profile",
            "application_id": APPLICATION_ID,
            "guild_id": GUILD_ID,
            "channel_id": CHANNEL_ID,
        },
    )
    assert connector.calls == [
        ("orphan-relay-connection", "missing-profile", "profile_unavailable")
    ]


def test_relay_readiness_is_installation_scoped_and_disconnect_clears_gateway_health(
    client: TestClient, auth: dict[str, str]
) -> None:
    class ConnectorStub:
        connected = True

    connector = ConnectorStub()
    client.app.state.settings.discord_application_id = APPLICATION_ID
    client.app.state.settings.discord_relay_url = "https://relay.test"
    client.app.state.relay_connector = connector
    event = {
        "type": "relay_readiness",
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "discord_ready": True,
        "heartbeat_healthy": True,
    }

    _dispatch(client, event)
    assert client.get("/api/v1/discord/status", headers=auth).json()["bot_ready"] is False
    _dispatch(client, {**event, "protocol_version": 1})
    ready = client.get("/api/v1/discord/status", headers=auth).json()
    assert ready["relay_configured"] is True
    assert ready["relay_url"] == "https://relay.test"
    assert ready["relay_online"] is True
    assert ready["discord_online"] is True
    assert ready["bot_ready"] is True

    connector.connected = False
    _dispatch(
        client,
        {
            "type": "relay_disconnected",
            "protocol_version": 1,
            "installation_id": client.app.state.settings.discord_relay_installation_id,
        },
    )
    disconnected = client.get("/api/v1/discord/status", headers=auth).json()
    assert disconnected["relay_online"] is False
    assert disconnected["discord_online"] is False
    assert disconnected["bot_ready"] is False
    client.app.state.relay_connector = None


def test_scoped_refresh_probes_and_republishes_only_the_exact_profile(
    client: TestClient, auth: dict[str, str]
) -> None:
    first_profile_id, first_connection_id = _seed_connection(client, auth)
    second_directory = (
        Path(__file__).parents[2] / "fixtures" / "servers" / "e2e-command-paper"
    )
    with client.app.state.session_factory() as db:
        owner = db.scalar(select(Administrator).where(Administrator.username == "owner"))
        assert owner is not None
        second_profile = Profile(
            name="Second Discord fixture",
            server_directory=str(second_directory),
            distribution="paper",
            is_fixture=True,
        )
        db.add(second_profile)
        db.flush()
        second_connection = DiscordConnection(
            admin_id=owner.id,
            profile_id=second_profile.id,
            relay_connection_id="relay-connection-2",
            application_id=APPLICATION_ID,
            guild_id=GUILD_ID,
            channel_id="900000000000000099",
            owner_user_id=OWNER_ID,
            authorized_user_ids=json.dumps([OWNER_ID]),
            authorized_role_ids="[]",
            share_address=True,
        )
        db.add(second_connection)
        first_connection = db.get(DiscordConnection, first_connection_id)
        assert first_connection is not None
        first_connection.share_address = True
        db.commit()
        second_profile_id = second_profile.id

    class DiscoveryStub:
        def __init__(self) -> None:
            self.forced: list[bool] = []

        async def discover(self, *, force: bool = False) -> dict[str, object]:
            self.forced.append(force)
            return {
                "available": False,
                "ip": None,
                "detail": "No public address is available.",
            }

    class ConnectorStub:
        connected = True

        def __init__(self) -> None:
            self.heartbeats: list[str] = []
            self.statuses: list[str] = []

        async def send_heartbeat(self, connection_id: str, **binding: object) -> None:
            assert set(binding) == {"profile_id", "application_id", "guild_id", "channel_id"}
            self.heartbeats.append(connection_id)

        async def send_status(
            self,
            connection_id: str,
            sequence: int,
            snapshot: dict[str, object],
            **binding: object,
        ) -> None:
            assert sequence == 1
            assert snapshot["protocol_version"] == 1
            assert set(binding) == {"profile_id", "application_id", "guild_id", "channel_id"}
            self.statuses.append(connection_id)

    discovery = DiscoveryStub()
    connector = ConnectorStub()
    client.app.state.public_ip_discovery = discovery
    client.app.state.relay_connector = connector
    pending = client.app.state.relay_pending_status
    pending.add((first_connection_id, first_profile_id))

    client.portal.call(lambda: client.app.state.relay_status_pass(scoped_wakeup=True))
    assert connector.heartbeats == []
    assert connector.statuses == ["relay-connection-1"]
    assert discovery.forced == [True]
    assert pending == set()

    client.portal.call(client.app.state.relay_heartbeat_pass)
    assert connector.heartbeats == ["relay-connection-1", "relay-connection-2"]
    assert connector.statuses == ["relay-connection-1"]
    assert discovery.forced == [True]

    client.portal.call(lambda: client.app.state.relay_status_pass(scoped_wakeup=False))
    assert connector.heartbeats == ["relay-connection-1", "relay-connection-2"]
    assert connector.statuses == ["relay-connection-1", "relay-connection-2"]
    assert discovery.forced == [True, False, False]
    with client.app.state.session_factory() as db:
        second = db.scalar(
            select(DiscordConnection).where(
                DiscordConnection.profile_id == second_profile_id
            )
        )
        assert second is not None and second.last_sequence == 1
    client.app.state.relay_connector = None


def test_terminal_revoke_deletes_disabled_binding_and_allows_fresh_pairing(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)

    class RelayStub:
        def __init__(self) -> None:
            self.revoked: list[str] = []

        def revoke_connection(self, relay_connection_id: str) -> None:
            self.revoked.append(relay_connection_id)

        def register_pairing(
            self, requested_profile_id: str, profile_name: str, code: str
        ) -> dict[str, object]:
            assert requested_profile_id == profile_id
            assert profile_name == "Discord event fixture"
            assert len(code) == 12
            return {"id": "relay-pairing-after-revoke"}

    relay = RelayStub()
    client.app.state.settings.discord_relay_url = "https://relay.test"
    client.app.state.relay_client = relay
    with client.app.state.session_factory() as db:
        connection = db.get(DiscordConnection, connection_id)
        assert connection is not None
        connection.enabled = False
        db.commit()

    blocked = client.post(
        "/api/v1/discord/pairings", headers=auth, json={"profile_id": profile_id}
    )
    assert blocked.status_code == 409

    revoked = client.delete(f"/api/v1/discord/connections/{connection_id}", headers=auth)
    assert revoked.status_code == 204, revoked.text
    assert relay.revoked == ["relay-connection-1"]
    with client.app.state.session_factory() as db:
        assert db.get(DiscordConnection, connection_id) is None

    paired = client.post(
        "/api/v1/discord/pairings", headers=auth, json={"profile_id": profile_id}
    )
    assert paired.status_code == 201, paired.text
    client.app.state.relay_client = None


def test_relay_terminal_revocation_requires_exact_binding_and_is_idempotent(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, connection_id = _seed_connection(client, auth)
    event: dict[str, object] = {
        "type": "connection_revoked",
        "protocol_version": 1,
        "installation_id": client.app.state.settings.discord_relay_installation_id,
        "connection_id": "relay-connection-1",
        "profile_id": profile_id,
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
    }

    _dispatch(client, {**event, "channel_id": "900000000000000099"})
    with client.app.state.session_factory() as db:
        assert db.get(DiscordConnection, connection_id) is not None

    _dispatch(client, event)
    _dispatch(client, event)
    with client.app.state.session_factory() as db:
        assert db.get(DiscordConnection, connection_id) is None


def test_profile_removal_uses_connected_connector_and_disconnected_client(
    client: TestClient, auth: dict[str, str]
) -> None:
    class ConnectorStub:
        def __init__(self, connected: bool, fail: bool = False) -> None:
            self.connected = connected
            self.fail = fail
            self.calls: list[tuple[str, str, str]] = []

        async def send_profile_binding_unavailable(
            self,
            connection_id: str,
            profile_id: str,
            *,
            application_id: str,
            guild_id: str,
            channel_id: str,
            reason: str,
        ) -> None:
            assert application_id == APPLICATION_ID
            assert guild_id == GUILD_ID
            assert channel_id.startswith("90000000000000000")
            self.calls.append((connection_id, profile_id, reason))
            if self.fail:
                raise RelayError("fake remote failure")

    class ClientStub:
        def __init__(self, fail: bool = False) -> None:
            self.fail = fail
            self.calls: list[str] = []

        def revoke_connection(self, connection_id: str) -> None:
            self.calls.append(connection_id)
            if self.fail:
                raise RelayError("fake remote failure")

    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    for name, connected, fail in (
        ("Connected removal", True, False),
        ("Disconnected removal", False, False),
        ("Remote failure removal", True, True),
    ):
        response = client.post(
            "/api/v1/profiles",
            headers=auth,
            json={"name": name, "path": str(fixture)},
        )
        assert response.status_code == 201, response.text
        profile_id = response.json()["id"]
        channel_id = {
            "Connected removal": "900000000000000006",
            "Disconnected removal": "900000000000000007",
            "Remote failure removal": "900000000000000008",
        }[name]
        with client.app.state.session_factory() as db:
            owner = db.scalar(select(Administrator).where(Administrator.username == "owner"))
            assert owner is not None
            db.add(
                DiscordConnection(
                    admin_id=owner.id,
                    profile_id=profile_id,
                    relay_connection_id=f"relay-{profile_id}",
                    application_id=APPLICATION_ID,
                    guild_id=GUILD_ID,
                    channel_id=channel_id,
                    owner_user_id=OWNER_ID,
                    authorized_user_ids=json.dumps([OWNER_ID]),
                    authorized_role_ids="[]",
                )
            )
            db.commit()
        connector = ConnectorStub(connected, fail)
        relay_client = ClientStub(fail)
        client.app.state.relay_connector = connector
        client.app.state.relay_client = relay_client
        removed = client.request(
            "DELETE",
            f"/api/v1/profiles/{profile_id}",
            headers=auth,
            json={"confirm_name": name, "delete_files": False},
        )
        assert removed.status_code == 200, removed.text
        if connected and not fail:
            assert connector.calls == [(f"relay-{profile_id}", profile_id, "profile_deleted")]
            assert relay_client.calls == []
        elif not connected:
            assert connector.calls == []
            assert relay_client.calls == [f"relay-{profile_id}"]
        else:
            assert connector.calls == [(f"relay-{profile_id}", profile_id, "profile_deleted")]
    client.app.state.relay_connector = None
    client.app.state.relay_client = None


def test_profile_removal_ignores_unexpected_connector_failure(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id, _ = _seed_connection(client, auth)

    class ConnectorStub:
        connected = True

        async def send_profile_binding_unavailable(
            self,
            _connection_id: str,
            _profile_id: str,
            *,
            application_id: str,
            guild_id: str,
            channel_id: str,
            reason: str,
        ) -> None:
            assert (application_id, guild_id, channel_id) == (
                APPLICATION_ID,
                GUILD_ID,
                CHANNEL_ID,
            )
            assert reason == "profile_deleted"
            raise OSError("websocket closed")

    client.app.state.relay_connector = ConnectorStub()
    removed = client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Discord event fixture", "delete_files": False},
    )
    assert removed.status_code == 200, removed.text
    with client.app.state.session_factory() as db:
        assert db.get(Profile, profile_id) is None
    client.app.state.relay_connector = None


class RotationClientStub:
    def __init__(self, *, fail_prepare: bool = False) -> None:
        self.fail_prepare = fail_prepare
        self.prepared: list[str] = []
        self.replaced: list[str] = []
        self.cancelled = 0

    def prepare_rotation(self, replacement_secret: str, *, ttl_seconds: int) -> dict[str, object]:
        if self.fail_prepare:
            raise RelayError("fake prepare failure")
        self.prepared.append(replacement_secret)
        return {"installation_id": "installation-1", "state": "pending"}

    def replace_identity(self, identity: object) -> None:
        self.replaced.append(str(getattr(identity, "connector_secret", "")))

    def cancel_rotation(self) -> dict[str, object]:
        self.cancelled += 1
        return {"state": "cancelled"}


class RotationConnectorStub:
    connected = True

    def __init__(self) -> None:
        self.replaced: list[str] = []

    async def replace_identity(self, identity: object) -> None:
        self.replaced.append(str(getattr(identity, "connector_secret", "")))


def test_connector_rotation_is_owner_csrf_protected_redacted_and_audited(
    client: TestClient, auth: dict[str, str]
) -> None:
    assert client.post("/api/v1/discord/connector/rotate").status_code in {401, 403}
    assert (
        client.post(
            "/api/v1/discord/connector/rotate", headers={"Origin": "http://testserver"}
        ).status_code
        == 403
    )
    relay = RotationClientStub()
    connector = RotationConnectorStub()
    client.app.state.relay_client = relay
    client.app.state.relay_connector = connector
    rotated = client.post("/api/v1/discord/connector/rotate", headers=auth)
    assert rotated.status_code == 200, rotated.text
    assert set(rotated.json()) == {"installation_id", "rotation_state", "detail"}
    assert rotated.json()["rotation_state"] == "reconnecting"
    assert relay.prepared and relay.replaced
    assert connector.replaced == relay.replaced
    assert relay.prepared[0] not in rotated.text
    with client.app.state.session_factory() as db:
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.category == "discord_connector_rotation")
        )
        assert audit is not None
        assert audit.result == "success"
        assert relay.prepared[0] not in audit.safe_detail
    activity = client.get("/api/v1/activity", headers=auth)
    assert activity.status_code == 200, activity.text
    assert relay.prepared[0] not in activity.text
    client.app.state.relay_client = None
    client.app.state.relay_connector = None


def test_connector_rotation_denies_real_viewer_even_with_csrf(
    client: TestClient, auth: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/accounts",
        headers=auth,
        json={"username": "discord-viewer", "password": "viewer password long enough"},
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://testserver"},
        json={"username": "discord-viewer", "password": "viewer password long enough"},
    )
    assert login.status_code == 200, login.text
    viewer_headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": login.json()["csrf_token"],
    }
    denied = client.post("/api/v1/discord/connector/rotate", headers=viewer_headers)
    assert denied.status_code == 403


def test_connector_rotation_prepare_failure_leaves_identity_unchanged(
    client: TestClient, auth: dict[str, str]
) -> None:
    before = ensure_relay_identity(client.app.state.settings.data_dir)
    relay = RotationClientStub(fail_prepare=True)
    client.app.state.relay_client = relay
    client.app.state.relay_connector = RotationConnectorStub()
    response = client.post("/api/v1/discord/connector/rotate", headers=auth)
    assert response.status_code == 503
    assert ensure_relay_identity(client.app.state.settings.data_dir) == before
    assert relay.replaced == []
    client.app.state.relay_client = None
    client.app.state.relay_connector = None


def test_connector_rotation_persistence_failure_cancels_without_lockout(
    client: TestClient, auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = ensure_relay_identity(client.app.state.settings.data_dir)
    relay = RotationClientStub()
    client.app.state.relay_client = relay
    client.app.state.relay_connector = RotationConnectorStub()
    monkeypatch.setattr(
        "blockstead.app.persist_relay_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("local write failed")),
    )
    response = client.post("/api/v1/discord/connector/rotate", headers=auth)
    assert response.status_code == 503
    assert ensure_relay_identity(client.app.state.settings.data_dir) == before
    assert relay.replaced == []
    assert relay.cancelled == 1
    client.app.state.relay_client = None
    client.app.state.relay_connector = None


def test_connector_rotation_reconnect_failure_restores_old_identity_and_cancels(
    client: TestClient, auth: dict[str, str]
) -> None:
    before = ensure_relay_identity(client.app.state.settings.data_dir)
    relay = RotationClientStub()

    class ConnectorStub:
        connected = True

        def __init__(self) -> None:
            self.attempts: list[str] = []

        async def replace_identity(self, identity: object) -> None:
            secret = str(getattr(identity, "connector_secret", ""))
            self.attempts.append(secret)
            if secret != before.connector_secret:
                raise OSError("new connector could not reconnect")

    connector = ConnectorStub()
    client.app.state.relay_client = relay
    client.app.state.relay_connector = connector
    response = client.post("/api/v1/discord/connector/rotate", headers=auth)
    assert response.status_code == 503, response.text
    assert ensure_relay_identity(client.app.state.settings.data_dir) == before
    assert client.app.state.settings.discord_relay_connector_secret == before.connector_secret
    assert relay.replaced == []
    assert relay.cancelled == 1
    assert connector.attempts[0] != before.connector_secret
    assert connector.attempts[-1] == before.connector_secret
    with client.app.state.session_factory() as db:
        assert db.scalar(
            select(AuditEvent).where(AuditEvent.category == "discord_connector_rotation")
        ) is None
    client.app.state.relay_client = None
    client.app.state.relay_connector = None


def test_connector_rotation_preserves_replacement_first_fallback_if_rollback_fails(
    client: TestClient, auth: dict[str, str]
) -> None:
    before = ensure_relay_identity(client.app.state.settings.data_dir)
    relay = RotationClientStub()

    class AmbiguousConnectorStub:
        connected = True

        async def replace_identity(self, identity: object) -> None:
            raise OSError("connector acknowledgement was lost")

    client.app.state.relay_client = relay
    client.app.state.relay_connector = AmbiguousConnectorStub()
    response = client.post("/api/v1/discord/connector/rotate", headers=auth)
    assert response.status_code == 503, response.text
    assert "staged replacement" in response.text
    state = load_relay_identity_state(client.app.state.settings.data_dir)
    assert state is not None
    assert state.active.connector_secret == relay.prepared[0]
    assert state.fallback == before
    assert relay.cancelled == 0
    client.app.state.relay_client = None
    client.app.state.relay_connector = None


def test_environment_managed_connector_rotation_returns_deployment_guidance(
    tmp_path: Path,
) -> None:
    fixture_root = Path(__file__).parents[2] / "fixtures" / "servers"
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path / "managed-data",
        server_root=fixture_root,
        allowed_origins="http://testserver",
        discord_relay_installation_id="managed-installation",
        discord_relay_connector_secret="managed-secret",  # noqa: S106 - fake test credential
    )
    with TestClient(create_app(settings)) as managed:
        setup = managed.post(
            "/api/v1/setup/admin",
            headers={"Origin": "http://testserver"},
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        headers = {"Origin": "http://testserver", "X-CSRF-Token": setup.json()["csrf_token"]}
        relay = RotationClientStub()
        managed.app.state.relay_client = relay
        response = managed.post("/api/v1/discord/connector/rotate", headers=headers)
        assert response.status_code == 409
        assert "managed by deployment settings" in response.text
        assert "managed-secret" not in response.text
        assert relay.prepared == []


def test_pair_confirmation_preserves_owner_and_safe_remote_state(
    client: TestClient, auth: dict[str, str]
) -> None:
    client.app.state.settings.discord_application_id = APPLICATION_ID
    client.app.state.settings.discord_relay_url = "https://relay.test"

    class PairingClientStub:
        profile_id = ""

        def register_pairing(
            self, profile_id: str, profile_name: str, code: str
        ) -> dict[str, object]:
            self.profile_id = profile_id
            return {"id": "relay-pairing-1"}

        def confirm_pairing(self, pairing_id: str) -> dict[str, object]:
            assert pairing_id == "relay-pairing-1"
            return {
                "protocol_version": 1,
                "id": "relay-connection-remote",
                "connection_id": "relay-connection-remote",
                "installation_id": (
                    client.app.state.settings.discord_relay_installation_id
                ),
                "profile_id": self.profile_id,
                "application_id": APPLICATION_ID,
                "guild_id": GUILD_ID,
                "channel_id": CHANNEL_ID,
                "share_address": False,
                "publish_address": False,
                "authorized_user_ids": ["900000000000000006", OWNER_ID, OWNER_ID],
                "authorized_role_ids": [ROLE_ID, ROLE_ID],
                "status_message_id": "900000000000000008",
                "last_delivery_result": "delivered",
                "last_delivery_at": EVENT_TIME,
                "last_delivery_detail": "secret=must-not-store",
            }

    client.app.state.relay_client = PairingClientStub()
    fixture = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"
    profile = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Remote state fixture", "path": str(fixture)},
    )
    assert profile.status_code == 201, profile.text
    pairing = client.post(
        "/api/v1/discord/pairings",
        headers=auth,
        json={"profile_id": profile.json()["id"]},
    )
    assert pairing.status_code == 201, pairing.text
    pairing_id = pairing.json()["id"]
    with client.app.state.session_factory() as db:
        record = db.get(DiscordPairing, pairing_id)
        assert record is not None
        record.relay_pairing_id = "relay-pairing-1"
        record.claimed_application_id = APPLICATION_ID
        record.claimed_guild_id = GUILD_ID
        record.claimed_channel_id = CHANNEL_ID
        record.claimed_user_id = OWNER_ID
        db.commit()

    confirmed = client.post(
        f"/api/v1/discord/pairings/{pairing_id}/confirm", headers=auth
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["authorized_user_ids"] == [OWNER_ID, "900000000000000006"]
    assert confirmed.json()["authorized_role_ids"] == [ROLE_ID]
    assert confirmed.json()["status_message_configured"] is True
    assert confirmed.json()["last_delivery_result"] == "delivered"
    assert confirmed.json()["last_delivery_detail"] == "Status message delivered."
    assert "secret=must-not-store" not in confirmed.text
    client.app.state.relay_client = None
