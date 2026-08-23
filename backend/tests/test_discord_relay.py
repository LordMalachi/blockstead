import asyncio
import json
from pathlib import Path

import pytest

from blockstead.config import Settings
from blockstead.discord_relay import (
    IDENTITY_VERSION,
    RelayClient,
    RelayConnector,
    RelayError,
    RelayIdentity,
    ensure_relay_identity,
    finalize_relay_identity,
    load_relay_identity_state,
    persist_relay_identity,
)


def test_ensure_relay_identity_creates_a_persistent_identity(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    first = ensure_relay_identity(data_dir)
    second = ensure_relay_identity(data_dir)

    assert first == second
    identity_path = data_dir / ".discord-relay-identity.json"
    assert identity_path.is_file()


def test_ensure_relay_identity_leaves_the_data_directory_listable(tmp_path: Path) -> None:
    """The headline regression, exercised at the real call site: writing and
    hardening the identity file must never lock the owner out of the data
    directory the way a raw ``chmod(0o700)`` did on Windows."""

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    ensure_relay_identity(data_dir)

    # Still listable, and a new file can still be created by the owner.
    names = [entry.name for entry in data_dir.iterdir()]
    assert ".discord-relay-identity.json" in names
    probe = data_dir / "probe.txt"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def test_ensure_relay_identity_prefers_configured_credentials(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    identity = ensure_relay_identity(data_dir, " configured-id ", " configured-secret ")

    assert identity.installation_id == "configured-id"
    assert identity.connector_secret == "configured-secret"  # noqa: S105 - fake test credential
    assert not (data_dir / ".discord-relay-identity.json").exists()


def test_generated_identity_can_be_replaced_atomically(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    original = ensure_relay_identity(data_dir)
    replacement = RelayIdentity(original.installation_id, "replacement-secret")

    persist_relay_identity(data_dir, replacement)

    assert ensure_relay_identity(data_dir) == replacement
    state = load_relay_identity_state(data_dir)
    assert state is not None
    assert state.version == IDENTITY_VERSION
    assert state.active == replacement
    assert state.fallback == original

    settings = Settings(
        _env_file=None,
        data_dir=data_dir,
        discord_relay_url="https://relay.example.test",
    )

    async def ignore_event(_: object) -> None:
        return None

    restarted = RelayConnector(settings, replacement, ignore_event)
    assert restarted._identity_candidates() == (replacement, original)
    finalize_relay_identity(data_dir, replacement)
    finalized = load_relay_identity_state(data_dir)
    assert finalized is not None and finalized.fallback is None


@pytest.mark.asyncio
async def test_connector_hello_requires_a_bounded_authenticated_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        discord_relay_url="https://relay.example.test",
    )
    identity = RelayIdentity("installation-1", "replacement-secret")

    async def ignore_event(_: object) -> None:
        return None

    connector = RelayConnector(settings, identity, ignore_event)

    class TimeoutSocket:
        sent = ""

        async def send(self, value: str) -> None:
            self.sent = value

        async def recv(self) -> str:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setattr("blockstead.discord_relay.HELLO_TIMEOUT_SECONDS", 0.01)
    socket = TimeoutSocket()
    with pytest.raises(RelayError) as timed_out:
        await connector._hello(socket, identity)
    assert identity.connector_secret not in str(timed_out.value)
    assert json.loads(socket.sent)["protocol_version"] == 1

    class RejectedSocket(TimeoutSocket):
        async def recv(self) -> str:
            return json.dumps(
                {
                    "type": "hello_ok",
                    "protocol_version": 1,
                    "installation_id": "different-installation",
                }
            )

    with pytest.raises(RelayError) as rejected:
        await connector._hello(RejectedSocket(), identity)
    assert identity.connector_secret not in str(rejected.value)


@pytest.mark.asyncio
async def test_connector_hello_accepts_only_the_exact_versioned_identity(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        discord_relay_url="https://relay.example.test",
    )
    identity = RelayIdentity("installation-1", "replacement-secret")

    async def ignore_event(_: object) -> None:
        return None

    connector = RelayConnector(settings, identity, ignore_event)

    class Socket:
        async def send(self, value: str) -> None:
            assert json.loads(value)["installation_id"] == identity.installation_id

        async def recv(self) -> str:
            return json.dumps(
                {
                    "type": "hello_ok",
                    "protocol_version": 1,
                    "installation_id": identity.installation_id,
                    "discord_ready": True,
                    "heartbeat_healthy": True,
                }
            )

    hello = await connector._hello(Socket(), identity)
    assert hello["discord_ready"] is True


def test_relay_client_exposes_rotation_control_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None, discord_relay_url="http://relay.test")
    client = RelayClient(settings, RelayIdentity("installation-1", "old-secret"))
    calls: list[tuple[str, str, dict[str, object]]] = []

    def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        calls.append((method, path, kwargs))
        return {"installation_id": "installation-1", "state": "safe"}

    monkeypatch.setattr(client, "_request", fake_request)
    try:
        client.prepare_rotation("replacement-secret", ttl_seconds=300)
        client.cancel_rotation()
        client.rotation_status()
    finally:
        client.close()

    assert [path for _, path, _ in calls] == [
        "/v1/installations/rotation/prepare",
        "/v1/installations/rotation/cancel",
        "/v1/installations/rotation/status",
    ]
    payload = calls[0][2]["json"]
    assert isinstance(payload, dict)
    assert payload["replacement_secret"] == "replacement-secret"  # noqa: S105 - fake credential
