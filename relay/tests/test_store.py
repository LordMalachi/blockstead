import pytest

from discord_relay.store import RelayStore

APP = "1535816544951476324"


def connected(
    store: RelayStore,
    installation: str,
    secret: str,
    profile: str,
    code: str,
    channel: str,
):
    pairing = store.register_pairing(
        installation_id=installation,
        connector_secret=secret,
        profile_id=profile,
        profile_name=profile,
        code=code,
    )
    claimed = store.claim_pairing(code, APP, "guild-1", channel, f"owner-{profile}")
    assert claimed.id == pairing.id
    return store.confirm_pairing(pairing.id, installation, secret)


def test_installations_and_channels_are_isolated() -> None:
    store = RelayStore()
    try:
        first = connected(
            store, "installation-one", "a" * 32, "profile-one", "CODEONE1", "channel-1"
        )
        second = connected(
            store, "installation-two", "b" * 32, "profile-two", "CODETWO2", "channel-2"
        )

        assert store.connection_for_discord(APP, "guild-1", "channel-1") == first
        assert store.connection_for_discord(APP, "guild-1", "channel-2") == second
        assert store.connection_for_discord(APP, "guild-1", "unknown") is None
        assert store.authenticate("installation-one", "b" * 32) is False

        first_snapshot = {"state": "running", "players": {"online": 1, "max": 20}}
        second_snapshot = {"state": "stopped", "players": {"online": 0, "max": 20}}
        assert store.save_snapshot(first.id, 2, first_snapshot) is True
        assert store.save_snapshot(first.id, 2, {"state": "spoofed"}) is False
        assert store.save_snapshot(first.id, 1, {"state": "old"}) is False
        assert store.save_snapshot(second.id, 1, second_snapshot) is True
        assert store.snapshot(first, 180)["state"] == "running"
        assert store.snapshot(second, 180)["state"] == "stopped"
    finally:
        store.close()


def test_pairing_is_single_use_and_expires() -> None:
    store = RelayStore()
    try:
        expired = store.register_pairing(
            installation_id="installation-expired",
            connector_secret="c" * 32,
            profile_id="profile-expired",
            profile_name="Expired",
            code="EXPIRED1",
            ttl_seconds=-1,
        )
        with pytest.raises(LookupError):
            store.claim_pairing("EXPIRED1", APP, "guild-1", "channel-1", "user-1")
        assert store.get_pairing(expired.id).status == "expired"

        connected_pairing = store.register_pairing(
            installation_id="installation-live",
            connector_secret="d" * 32,
            profile_id="profile-live",
            profile_name="Live",
            code="LIVEPAIR",
        )
        store.claim_pairing("LIVEPAIR", APP, "guild-1", "channel-9", "user-9")
        with pytest.raises(LookupError):
            store.claim_pairing("LIVEPAIR", APP, "guild-1", "channel-10", "user-10")
        assert store.get_pairing(connected_pairing.id).claimed_at is not None
    finally:
        store.close()


def test_pairing_rejects_active_channel_conflicts() -> None:
    store = RelayStore()
    try:
        connected(store, "installation-one", "a" * 32, "profile-one", "CHANNEL1", "channel-1")
        store.register_pairing(
            installation_id="installation-two",
            connector_secret="b" * 32,
            profile_id="profile-two",
            profile_name="Two",
            code="CHANNEL2",
        )
        with pytest.raises(ValueError, match="already paired"):
            store.claim_pairing("CHANNEL2", APP, "guild-1", "channel-1", "user-2")
    finally:
        store.close()


def test_duplicate_claim_does_not_expire_the_pending_confirmation() -> None:
    store = RelayStore()
    try:
        pairing = store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="DUPLICATE1",
        )
        claimed = store.claim_pairing("DUPLICATE1", APP, "guild-1", "channel-1", "user-1")
        with pytest.raises(LookupError):
            store.claim_pairing("DUPLICATE1", APP, "guild-1", "channel-1", "user-1")
        confirmed = store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        assert confirmed.channel_id == claimed.claimed_channel_id
    finally:
        store.close()


def test_connection_changes_require_the_connector_secret() -> None:
    store = RelayStore()
    try:
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "AUTHCHECK", "channel-1"
        )
        with pytest.raises(PermissionError):
            store.update_connection(
                connection.id, "installation-one", "b" * 32, publish_address=True
            )
        unchanged = store.connection(connection.id)
        assert unchanged is not None and unchanged.publish_address is False
        updated = store.update_connection(
            connection.id, "installation-one", "a" * 32, publish_address=True
        )
        assert updated.publish_address is True
    finally:
        store.close()
