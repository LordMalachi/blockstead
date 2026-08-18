from pathlib import Path

import pytest

from discord_relay.app import RelayRuntime
from discord_relay.config import RelaySettings
from discord_relay.protocol import RelayInteraction


def interaction(
    command: str, *, channel: str = "channel-1", user: str = "user-1"
) -> RelayInteraction:
    return RelayInteraction(
        interaction_id="interaction-1",
        interaction_token="interaction-token",  # noqa: S106
        application_id="1535816544951476324",
        guild_id="guild-1",
        channel_id=channel,
        user_id=user,
        subcommand=command,
        options={},
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
        assert "not paired" in await runtime.interaction(interaction("status"))
        assert "first-time setup" in await runtime.interaction(interaction("setup"))
    finally:
        runtime.store.close()


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
            "PAIRCODE", "1535816544951476324", "guild-1", "channel-1", "user-1"
        )
        connection = runtime.store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        assert "disabled" in await runtime.interaction(interaction("address"))
        runtime.store.update_connection(
            connection.id, "installation-one", "a" * 32, publish_address=True
        )
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
            "REFRESH01", "1535816544951476324", "guild-1", "channel-1", "user-1"
        )
        confirmed = runtime.store.confirm_pairing(connection.id, "installation-one", "a" * 32)
        runtime.max_refresh_entries = 2

        assert "requested" in await runtime.interaction(interaction("refresh", user="user-1"))
        assert "requested" in await runtime.interaction(interaction("refresh", user="user-2"))
        assert "requested" in await runtime.interaction(interaction("refresh", user="user-3"))
        assert len(runtime.refreshes) == 2
        assert (confirmed.id, "user-1") not in runtime.refreshes
    finally:
        runtime.store.close()
