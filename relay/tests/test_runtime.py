import asyncio
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from discord_relay.app import RelayRuntime, bounded_snapshot, create_app
from discord_relay.config import RelaySettings
from discord_relay.discord import DiscordError, DiscordRest
from discord_relay.protocol import RelayInteraction

APPLICATION_ID = "1535816544951476324"
INTERACTION_ID = "920000000000000001"
GUILD_ID = "920000000000000002"
CHANNEL_ONE = "920000000000000003"
CHANNEL_TWO = "920000000000000004"
CHANNEL_UNKNOWN = "920000000000000099"
USER_ONE = "920000000000000011"
USER_TWO = "920000000000000012"
USER_THREE = "920000000000000013"
STATUS_MESSAGE_ID = "920000000000000021"


def test_snapshot_v1_is_exact_bounded_and_accepts_unknown_process_state() -> None:
    snapshot: dict[str, object] = {
        "protocol_version": 1,
        "state": "unknown",
        "players": {"online": 0, "max": 20},
        "public": {"state": "port_unverified", "address": "[2001:db8::1]:25565"},
        "host_observed_at": "2026-08-23T12:00:00-05:00",
    }

    normalized = bounded_snapshot(snapshot, share_address=True)

    assert normalized["state"] == "unknown"
    assert normalized["public"] == {
        "state": "port_unverified",
        "address": "[2001:db8::1]:25565",
    }
    assert normalized["host_observed_at"] == "2026-08-23T17:00:00+00:00"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("protocol_version"),
        lambda value: value.update({"unexpected": True}),
        lambda value: value.update({"state": "RUNNING"}),
        lambda value: value.update({"players": {"online": 21, "max": 20}}),
        lambda value: value.update({"players": {"online": None, "max": 20}}),
        lambda value: value.update(
            {"public": {"state": "port_unverified", "address": "2001:db8::1:25565"}}
        ),
        lambda value: value.update({"public": {"state": "public", "address": "8.8.8.8:1"}}),
        lambda value: value.update({"host_observed_at": "2026-08-23T12:00:00"}),
    ],
)
def test_snapshot_v1_rejects_missing_unknown_or_malformed_evidence(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    snapshot: dict[str, object] = {
        "protocol_version": 1,
        "state": "running",
        "players": {"online": 1, "max": 20},
        "public": {"state": "port_unverified", "address": "8.8.8.8:25565"},
        "host_observed_at": "2026-08-23T12:00:00+00:00",
    }
    candidate = deepcopy(snapshot)
    mutate(candidate)

    with pytest.raises(ValueError):
        bounded_snapshot(candidate, share_address=True)


def test_snapshot_v1_rejects_address_when_connection_does_not_share() -> None:
    snapshot: dict[str, object] = {
        "protocol_version": 1,
        "state": "running",
        "players": {"online": None, "max": None},
        "public": {"state": "port_unverified", "address": "8.8.8.8:25565"},
        "host_observed_at": "2026-08-23T12:00:00+00:00",
    }

    with pytest.raises(ValueError, match="sharing is disabled"):
        bounded_snapshot(snapshot, share_address=False)


class CaptureSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)

    async def close(self, **_: object) -> None:
        return None


class FakeRest:
    async def create_message(self, channel_id: str, content: str) -> str:
        return STATUS_MESSAGE_ID

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
        return None


class FakeGateway:
    def __init__(self) -> None:
        self.rest = FakeRest()


def interaction(
    command: str,
    *,
    channel: str = CHANNEL_ONE,
    user: str = USER_ONE,
    roles: tuple[str, ...] = (),
) -> RelayInteraction:
    return RelayInteraction(
        interaction_id=INTERACTION_ID,
        interaction_token="interaction-token",  # noqa: S106
        application_id=APPLICATION_ID,
        guild_id=GUILD_ID,
        channel_id=channel,
        user_id=user,
        subcommand=command,
        options={},
        role_ids=roles,
    )


@pytest.mark.asyncio
async def test_unknown_channel_receives_generic_response(tmp_path: Path) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        assert (
            (await runtime.interaction(interaction("status"))).content == runtime.generic_denial
        )
        assert "first-time setup" in await runtime.interaction(interaction("setup"))
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_only_explicit_principals_can_read_and_unknown_contexts_match_denial(
    tmp_path: Path,
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        pairing = runtime.store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="AUTHROLE1",
        )
        runtime.store.claim_pairing(
            "AUTHROLE1",
            APPLICATION_ID,
            GUILD_ID,
            CHANNEL_ONE,
            "123456789012345678",
        )
        connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        runtime.store.update_connection(
            connection.id,
            "installation-one",
            "a" * 32,
            authorized_user_ids=["123456789012345678", "123456789012345679"],
            authorized_role_ids=["987654321098765432"],
        )
        denied = await runtime.interaction(
            interaction("status", user="123456789012345680")
        )
        role_allowed = await runtime.interaction(
            interaction("status", user="123456789012345680", roles=("987654321098765432",))
        )
        unknown = await runtime.interaction(
            interaction("status", channel=CHANNEL_UNKNOWN, user="123456789012345680")
        )
        assert denied.content == unknown.content
        assert denied.ephemeral is True
        assert "waiting" in role_allowed.content
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_setup_is_public_help_is_ephemeral_and_pair_attempts_are_bounded(
    tmp_path: Path,
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        setup = await runtime.interaction(interaction("setup"))
        help_reply = await runtime.interaction(interaction("help"))
        assert setup.ephemeral is False
        assert help_reply.ephemeral is True
        runtime.pair_attempt_limit = 1
        first = await runtime.interaction(interaction("pair"))
        second = await runtime.interaction(interaction("pair"))
        assert first.content != ""
        assert second.content == runtime.generic_denial
        assert len(runtime.pair_attempts) == 1
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_unknown_commands_use_the_same_denial_for_all_channel_contexts(
    tmp_path: Path,
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        pairing = runtime.store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="UNKNOWN01",
        )
        runtime.store.claim_pairing(
            "UNKNOWN01", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
        )
        runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        paired_authorized = await runtime.interaction(interaction("unsupported"))
        paired_unauthorized = await runtime.interaction(
            interaction("unsupported", user=USER_TWO)
        )
        unknown_channel = await runtime.interaction(
            interaction("unsupported", channel=CHANNEL_UNKNOWN, user=USER_TWO)
        )
        assert paired_authorized.content == runtime.generic_denial
        assert paired_authorized.content == paired_unauthorized.content == unknown_channel.content
        assert paired_authorized.ephemeral is True
        audits = [
            audit for audit in runtime.store.audits(limit=20) if audit.command == "unsupported"
        ]
        assert len(audits) == 3
        assert all(audit.outcome == "denied" for audit in audits)
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_audit_and_delivery_events_include_only_safe_binding_fields(tmp_path: Path) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        pairing = runtime.store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="EVENTS001",
        )
        runtime.store.claim_pairing(
            "EVENTS001", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
        )
        connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        socket = CaptureSocket()
        runtime.hosts[connection.installation_id] = socket  # type: ignore[assignment]
        await runtime.interaction(interaction("status"))
        audit = next(message for message in socket.messages if message["type"] == "command_audit")
        assert audit["installation_id"] == "installation-one"
        assert audit["profile_id"] == "profile-one"
        assert audit["connection_id"] == connection.id
        assert audit["application_id"] == connection.application_id
        assert audit["guild_id"] == connection.guild_id
        assert audit["channel_id"] == connection.channel_id
        assert {
            "options",
            "content",
            "address",
            "snapshot",
            "connector_secret",
            "pairing_code",
        }.isdisjoint(audit)

        runtime.gateway = FakeGateway()  # type: ignore[assignment]
        await runtime.publish(connection)
        delivery = next(
            message for message in socket.messages if message["type"] == "connection_delivery"
        )
        assert delivery["installation_id"] == "installation-one"
        assert delivery["profile_id"] == "profile-one"
        assert delivery["connection_id"] == connection.id
        assert delivery["application_id"] == connection.application_id
        assert delivery["guild_id"] == connection.guild_id
        assert delivery["channel_id"] == connection.channel_id
        assert delivery["status_message_id"] == STATUS_MESSAGE_ID
        assert delivery["result"] == "delivered"
        assert delivery["detail"] == "Status message delivered."
        assert delivery["timestamp"]
        assert {
            "options",
            "content",
            "address",
            "snapshot",
            "connector_secret",
            "pairing_code",
        }.isdisjoint(delivery)
    finally:
        runtime.store.close()


def test_reconnect_replays_enabled_connections_and_terminal_revocations_for_installation(
    tmp_path: Path,
) -> None:
    app = create_app(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    runtime = app.state.runtime
    first_pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="RECONNECT1",
    )
    runtime.store.claim_pairing(
        "RECONNECT1", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    first = runtime.store.confirm_pairing(first_pairing.id, "installation-one", "a" * 32)
    runtime.store.set_status_message(first.id, STATUS_MESSAGE_ID)
    second_pairing = runtime.store.register_pairing(
        installation_id="installation-two",
        connector_secret="b" * 32,
        profile_id="profile-two",
        profile_name="Two",
        code="RECONNECT2",
    )
    runtime.store.claim_pairing(
        "RECONNECT2", APPLICATION_ID, GUILD_ID, CHANNEL_TWO, USER_TWO
    )
    second = runtime.store.confirm_pairing(second_pairing.id, "installation-two", "b" * 32)
    revoked_pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-revoked",
        profile_name="Revoked",
        code="REVOKED001",
    )
    runtime.store.claim_pairing(
        "REVOKED001", APPLICATION_ID, GUILD_ID, CHANNEL_UNKNOWN, USER_ONE
    )
    revoked = runtime.store.confirm_pairing(
        revoked_pairing.id, "installation-one", "a" * 32
    )
    revoked = runtime.store.revoke_connection(
        revoked.id, "installation-one", "a" * 32
    )
    assert revoked.revoked_at is not None
    with TestClient(app) as client:
        with client.websocket_connect("/v1/connect") as missing_version:
            missing_version.send_json(
                {
                    "type": "hello",
                    "installation_id": "installation-one",
                    "connector_secret": "a" * 32,
                }
            )
            with pytest.raises(WebSocketDisconnect):
                missing_version.receive_json()
        with client.websocket_connect("/v1/connect") as socket:
            socket.send_json(
                {
                    "type": "hello",
                    "protocol_version": 1,
                    "installation_id": "installation-one",
                    "connector_secret": "a" * 32,
                }
            )
            hello = socket.receive_json()
            assert hello["type"] == "hello_ok"
            assert hello["protocol_version"] == 1
            assert hello["installation_id"] == "installation-one"
            replay = socket.receive_json()
            assert replay["type"] == "connection_activated"
            assert replay["connection_id"] == first.id
            assert replay["id"] == first.id
            assert replay["profile_id"] == "profile-one"
            assert replay["status_message_id"] == STATUS_MESSAGE_ID
            assert replay["protocol_version"] == 1
            assert replay["installation_id"] == "installation-one"
            assert replay["application_id"] == APPLICATION_ID
            assert replay["guild_id"] == GUILD_ID
            assert replay["channel_id"] == CHANNEL_ONE
            assert second.id not in {
                message.get("connection_id")
                for message in (replay,)
                if isinstance(message, dict)
            }
            tombstone = socket.receive_json()
            assert tombstone == {
                "type": "connection_revoked",
                "protocol_version": 1,
                "installation_id": "installation-one",
                "connection_id": revoked.id,
                "profile_id": "profile-revoked",
                "application_id": APPLICATION_ID,
                "guild_id": GUILD_ID,
                "channel_id": CHANNEL_UNKNOWN,
                "revoked_at": revoked.revoked_at.isoformat(),
            }
            socket.send_json({"type": "heartbeat", "connection_id": first.id})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        with client.websocket_connect("/v1/connect") as malformed_status:
            malformed_status.send_json(
                {
                    "type": "hello",
                    "protocol_version": 1,
                    "installation_id": "installation-one",
                    "connector_secret": "a" * 32,
                }
            )
            assert malformed_status.receive_json()["type"] == "hello_ok"
            assert malformed_status.receive_json()["type"] == "connection_activated"
            assert malformed_status.receive_json()["type"] == "connection_revoked"
            malformed_status.send_json(
                {
                    "type": "heartbeat",
                    "protocol_version": 1,
                    "installation_id": "installation-one",
                    "connection_id": first.id,
                    "profile_id": first.profile_id,
                    "application_id": first.application_id,
                    "guild_id": first.guild_id,
                    "channel_id": first.channel_id,
                }
            )
            heartbeat = malformed_status.receive_json()
            assert heartbeat["type"] == "connection_heartbeat"
            assert heartbeat["connection_id"] == first.id
            assert heartbeat["received_at"]
            malformed_status.send_json(
                {
                    "type": "status",
                    "protocol_version": 1,
                    "installation_id": "installation-one",
                    "connection_id": first.id,
                    "profile_id": first.profile_id,
                    "application_id": first.application_id,
                    "guild_id": first.guild_id,
                    "channel_id": first.channel_id,
                    "sequence": "1",
                    "snapshot": {
                        "protocol_version": 1,
                        "state": "running",
                        "players": {"online": 1, "max": 20},
                        "public": {"state": "unknown"},
                        "host_observed_at": "2026-08-23T12:00:00+00:00",
                    },
                }
            )
            with pytest.raises(WebSocketDisconnect):
                malformed_status.receive_json()


def test_rotation_rejects_same_or_malformed_replacement_without_changing_pending_state(
    tmp_path: Path,
) -> None:
    store = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    ).store
    try:
        store.register_installation("installation-one", "a" * 32)
        prepared = store.prepare_rotation("installation-one", "a" * 32, "b" * 32)
        with pytest.raises(ValueError):
            store.prepare_rotation("installation-one", "a" * 32, "a" * 32)
        unchanged = store.rotation_status("installation-one", "a" * 32)
        assert unchanged.pending is True
        assert unchanged.expires_at == prepared.expires_at
        with pytest.raises(ValueError):
            store.prepare_rotation("installation-one", "a" * 32, object())  # type: ignore[arg-type]
        still_pending = store.rotation_status("installation-one", "a" * 32)
        assert still_pending.expires_at == prepared.expires_at
    finally:
        store.close()


def test_rotation_prepare_api_returns_safe_422_for_same_credential(tmp_path: Path) -> None:
    app = create_app(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    with TestClient(app) as client:
        assert client.post(
            "/v1/installations/register",
            json={"installation_id": "installation-one", "connector_secret": "a" * 32},
        ).is_success
        response = client.post(
            "/v1/installations/rotation/prepare",
            json={
                "installation_id": "installation-one",
                "connector_secret": "a" * 32,
                "replacement_secret": "a" * 32,
            },
        )
        assert response.status_code == 422
        assert "a" * 32 not in response.text
        assert "pending_connector_secret_hash" not in response.text


@pytest.mark.asyncio
async def test_address_obeys_connection_sharing_toggle(tmp_path: Path) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        pairing = runtime.store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="PAIRCODE",
        )
        runtime.store.claim_pairing(
            "PAIRCODE", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
        )
        connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        assert "disabled" in await runtime.interaction(interaction("address"))
        runtime.store.update_connection(
            connection.id,
            "installation-one",
            "a" * 32,
            share_address=True,
            publish_address=True,
        )
        runtime.interaction_cooldown_seconds = 0
        assert "unavailable" in await runtime.interaction(interaction("address"))
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_refresh_cooldown_map_stays_bounded(tmp_path: Path) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id="1535816544951476324",
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    try:
        connection = runtime.store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="REFRESH01",
        )
        runtime.store.claim_pairing(
            "REFRESH01", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
        )
        confirmed = runtime.store.confirm_pairing(connection.id, "installation-one", "a" * 32)
        runtime.max_refresh_entries = 2

        assert "requested" in await runtime.interaction(interaction("refresh", user=USER_ONE))
        assert (
            (await runtime.interaction(interaction("refresh", user=USER_TWO))).content
            == runtime.generic_denial
        )
        assert (
            (await runtime.interaction(interaction("refresh", user=USER_THREE))).content
            == runtime.generic_denial
        )
        assert len(runtime.refreshes) == 1
        assert (confirmed.id, USER_ONE) in runtime.refreshes
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_delivery_retries_are_bounded_and_report_safe_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id=APPLICATION_ID,
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="RETRY001",
    )
    runtime.store.claim_pairing(
        "RETRY001", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
    socket = CaptureSocket()
    runtime.hosts[connection.installation_id] = socket  # type: ignore[assignment]

    class FailingRest:
        calls = 0

        async def create_message(self, channel_id: str, content: str) -> str:
            self.calls += 1
            raise DiscordError("temporary", status_code=500)

        async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
            raise AssertionError("no status message should exist")

    class Gateway:
        rest = FailingRest()

    delays: list[float] = []

    async def no_wait(_connection_id: str, delay: float) -> bool:
        delays.append(delay)
        return False

    monkeypatch.setattr(runtime, "_wait_for_retry", no_wait)
    runtime.gateway = Gateway()  # type: ignore[assignment]
    try:
        await runtime.publish(connection)
        assert Gateway.rest.calls == 5
        assert delays == [1.0, 2.0, 4.0, 8.0]
        evidence = [
            message for message in socket.messages if message["type"] == "connection_delivery"
        ]
        assert [message["result"] for message in evidence] == [
            "retrying",
            "retrying",
            "retrying",
            "retrying",
            "failed",
        ]
        assert all("temporary" not in str(message) for message in evidence)
    finally:
        runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "retry_after", "expected_calls", "expected_delays"),
    [
        (429, 17.0, 5, [17.0, 17.0, 17.0, 17.0]),
        (None, None, 5, [1.0, 2.0, 4.0, 8.0]),
        (400, None, 1, []),
    ],
)
async def test_delivery_error_policy_handles_rate_limits_network_and_terminal_4xx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int | None,
    retry_after: float | None,
    expected_calls: int,
    expected_delays: list[float],
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id=APPLICATION_ID,
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="POLICY01",
    )
    runtime.store.claim_pairing(
        "POLICY01", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)

    class ErrorRest:
        def __init__(self) -> None:
            self.calls = 0

        async def create_message(self, channel_id: str, content: str) -> str:
            self.calls += 1
            raise DiscordError(
                "safe failure", status_code=status_code, retry_after=retry_after
            )

        async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
            raise AssertionError("no status message should exist")

    class Gateway:
        def __init__(self) -> None:
            self.rest = ErrorRest()

    gateway = Gateway()
    runtime.gateway = gateway  # type: ignore[assignment]
    delays: list[float] = []

    async def no_wait(_connection_id: str, delay: float) -> bool:
        delays.append(delay)
        return False

    monkeypatch.setattr(runtime, "_wait_for_retry", no_wait)
    try:
        await runtime.publish(connection)
        assert gateway.rest.calls == expected_calls
        assert delays == expected_delays
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_delivery_queue_coalesces_a_superseded_retry_to_the_latest_value(
    tmp_path: Path,
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id=APPLICATION_ID,
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="COALESCE",
    )
    runtime.store.claim_pairing(
        "COALESCE", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
    socket = CaptureSocket()
    runtime.hosts[connection.installation_id] = socket  # type: ignore[assignment]
    first_attempt = asyncio.Event()

    class CoalescingRest:
        def __init__(self) -> None:
            self.contents: list[str] = []

        async def create_message(self, channel_id: str, content: str) -> str:
            self.contents.append(content)
            if len(self.contents) == 1:
                first_attempt.set()
                raise DiscordError("temporary", status_code=500)
            return STATUS_MESSAGE_ID

        async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
            raise AssertionError("the coalesced delivery creates only the latest value")

    class Gateway:
        def __init__(self) -> None:
            self.rest = CoalescingRest()

    gateway = Gateway()
    runtime.gateway = gateway  # type: ignore[assignment]
    try:
        initial = asyncio.create_task(runtime.publish(connection))
        await first_attempt.wait()
        assert runtime.store.save_snapshot(
            connection.id,
            "installation-one",
            "a" * 32,
            1,
            {"state": "running", "players": {"online": 2, "max": 20}},
        )
        updated = runtime.store.connection(connection.id)
        assert updated is not None
        await runtime.publish(updated)
        await initial

        assert len(gateway.rest.contents) == 2
        assert "waiting" in gateway.rest.contents[0].lower()
        assert "running" in gateway.rest.contents[1].lower()
        evidence = [
            message["result"]
            for message in socket.messages
            if message["type"] == "connection_delivery"
        ]
        assert evidence == ["retrying", "delivered"]
    finally:
        runtime.store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retry_value", "expected"),
    [(0, 1.0), (999, 300.0), ("17.5", 17.5)],
)
async def test_discord_retry_after_is_clamped_to_safe_bounds(
    retry_value: int | str, expected: float
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"retry_after": retry_value}, request=request)

    rest = DiscordRest(APPLICATION_ID, "not-a-real-token")
    await rest._client.aclose()
    rest._client = httpx.AsyncClient(
        base_url="https://discord.test", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(DiscordError) as raised:
            await rest.request("POST", "/messages")
        assert raised.value.retry_after == expected
    finally:
        await rest.close()


@pytest.mark.asyncio
async def test_every_discord_content_request_suppresses_mentions() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert isinstance(payload, dict)
        bodies.append(payload)
        response = (
            {"id": STATUS_MESSAGE_ID}
            if request.method == "POST" and request.url.path.endswith("/messages")
            else None
        )
        return httpx.Response(200 if response else 204, json=response, request=request)

    rest = DiscordRest(APPLICATION_ID, "not-a-real-token")
    await rest._client.aclose()
    rest._client = httpx.AsyncClient(
        base_url="https://discord.test", transport=httpx.MockTransport(handler)
    )
    try:
        marker = "@everyone @here <@920000000000000011> <@&920000000000000012>"
        await rest.create_message(CHANNEL_ONE, marker)
        await rest.edit_message(CHANNEL_ONE, STATUS_MESSAGE_ID, marker)
        await rest.respond(interaction("status"), marker)
    finally:
        await rest.close()

    assert bodies[0]["allowed_mentions"] == {"parse": []}
    assert bodies[1]["allowed_mentions"] == {"parse": []}
    callback_data = bodies[2]["data"]
    assert isinstance(callback_data, dict)
    assert callback_data["allowed_mentions"] == {"parse": []}


@pytest.mark.asyncio
async def test_missing_status_message_is_recreated_once(tmp_path: Path) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id=APPLICATION_ID,
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
        )
    )
    pairing = runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="RECREATE",
    )
    runtime.store.claim_pairing(
        "RECREATE", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
    runtime.store.set_status_message(connection.id, STATUS_MESSAGE_ID)

    class RecreateRest:
        edits = 0
        creates = 0

        async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
            self.edits += 1
            raise DiscordError("missing", status_code=404)

        async def create_message(self, channel_id: str, content: str) -> str:
            self.creates += 1
            return "920000000000000022"

    class Gateway:
        rest = RecreateRest()

    runtime.gateway = Gateway()  # type: ignore[assignment]
    try:
        current = runtime.store.connection(connection.id)
        assert current is not None
        await runtime.publish(current)
        updated = runtime.store.connection(connection.id)
        assert updated is not None and updated.status_message_id == "920000000000000022"
        assert updated.last_delivered_hash is not None
        assert Gateway.rest.edits == 1
        assert Gateway.rest.creates == 1
    finally:
        runtime.store.close()


@pytest.mark.asyncio
async def test_delivery_hash_survives_restart_and_tracks_fresh_stale_fresh(
    tmp_path: Path,
) -> None:
    path = tmp_path / "relay.db"
    settings = RelaySettings(
        _env_file=None,
        application_id=APPLICATION_ID,
        bot_token="not-a-real-token",  # noqa: S106
        database_path=path,
        stale_after_seconds=30,
    )
    first_runtime = RelayRuntime(settings)
    pairing = first_runtime.store.register_pairing(
        installation_id="installation-one",
        connector_secret="a" * 32,
        profile_id="profile-one",
        profile_name="One",
        code="HASH0001",
    )
    first_runtime.store.claim_pairing(
        "HASH0001", APPLICATION_ID, GUILD_ID, CHANNEL_ONE, USER_ONE
    )
    connection = first_runtime.store.confirm_pairing(
        pairing.id, "installation-one", "a" * 32
    )
    first_runtime.store.set_status_message(connection.id, STATUS_MESSAGE_ID)
    assert first_runtime.store.save_snapshot(
        connection.id,
        "installation-one",
        "a" * 32,
        1,
        {"state": "running", "players": {"online": 1, "max": 20}},
    )

    class EditingRest:
        def __init__(self) -> None:
            self.edits: list[tuple[str, str]] = []

        async def edit_message(self, channel_id: str, message_id: str, content: str) -> None:
            assert message_id == STATUS_MESSAGE_ID
            self.edits.append((message_id, content))

        async def create_message(self, channel_id: str, content: str) -> str:
            raise AssertionError("restart reconciliation must reuse the status message")

    class Gateway:
        def __init__(self) -> None:
            self.rest = EditingRest()

    first_gateway = Gateway()
    first_runtime.gateway = first_gateway  # type: ignore[assignment]
    current = first_runtime.store.connection(connection.id)
    assert current is not None
    await first_runtime.publish(current)
    assert len(first_gateway.rest.edits) == 1
    first_runtime.store.close()

    restarted = RelayRuntime(settings)
    restarted_gateway = Gateway()
    restarted.gateway = restarted_gateway  # type: ignore[assignment]
    try:
        await restarted.reconcile_deliveries()
        assert restarted_gateway.rest.edits == []

        restarted.store._db.execute(
            "UPDATE latest_snapshots SET observed_at = ? WHERE connection_id = ?",
            ("2000-01-01T00:00:00+00:00", connection.id),
        )
        await restarted.reconcile_deliveries()
        assert len(restarted_gateway.rest.edits) == 1
        assert "stale" in restarted_gateway.rest.edits[-1][1]

        assert restarted.store.save_snapshot(
            connection.id,
            "installation-one",
            "a" * 32,
            2,
            {"state": "running", "players": {"online": 1, "max": 20}},
        )
        await restarted.reconcile_deliveries()
        assert len(restarted_gateway.rest.edits) == 2
        assert "stale" not in restarted_gateway.rest.edits[-1][1]
        await restarted.reconcile_deliveries()
        assert len(restarted_gateway.rest.edits) == 2
    finally:
        restarted.store.close()


@pytest.mark.asyncio
async def test_delivery_scan_uses_one_quarter_of_stale_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = RelayRuntime(
        RelaySettings(
            _env_file=None,
            application_id=APPLICATION_ID,
            bot_token="not-a-real-token",  # noqa: S106
            database_path=tmp_path / "relay.db",
            stale_after_seconds=30,
        )
    )
    intervals: list[float] = []

    async def stop_after_first_sleep(interval: float) -> None:
        intervals.append(interval)
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)
    try:
        with pytest.raises(asyncio.CancelledError):
            await runtime.delivery_scan_loop()
        assert intervals == [7.5]
    finally:
        runtime.store.close()
