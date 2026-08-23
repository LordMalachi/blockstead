import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from discord_relay.store import RelayStore

APP = "1535816544951476324"
GUILD = "900000000000000001"
CHANNEL_ONE = "900000000000000002"
CHANNEL_TWO = "900000000000000003"
CHANNEL_NINE = "900000000000000009"
CHANNEL_TEN = "900000000000000010"
USER_ONE = "910000000000000001"
USER_TWO = "910000000000000002"


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
    owner = str(910000000000000000 + sum(ord(character) for character in profile))
    claimed = store.claim_pairing(code, APP, GUILD, channel, owner)
    assert claimed.id == pairing.id
    return store.confirm_pairing(pairing.id, installation, secret)


def test_installations_and_channels_are_isolated() -> None:
    store = RelayStore()
    try:
        first = connected(
            store, "installation-one", "a" * 32, "profile-one", "CODEONE1", CHANNEL_ONE
        )
        second = connected(
            store, "installation-two", "b" * 32, "profile-two", "CODETWO2", CHANNEL_TWO
        )

        assert store.connection_for_discord(APP, GUILD, CHANNEL_ONE) == first
        assert store.connection_for_discord(APP, GUILD, CHANNEL_TWO) == second
        assert store.connection_for_discord(APP, GUILD, "900000000000000099") is None
        assert store.authenticate("installation-one", "b" * 32) is False

        first_snapshot = {"state": "running", "players": {"online": 1, "max": 20}}
        second_snapshot = {"state": "stopped", "players": {"online": 0, "max": 20}}
        assert store.save_snapshot(first.id, "installation-one", "a" * 32, 2, first_snapshot)
        assert not store.save_snapshot(
            first.id, "installation-one", "a" * 32, 2, {"state": "spoofed"}
        )
        assert not store.save_snapshot(
            first.id, "installation-one", "a" * 32, 1, {"state": "old"}
        )
        assert store.save_snapshot(second.id, "installation-two", "b" * 32, 1, second_snapshot)
        assert store.snapshot(first, 180)["state"] == "running"
        assert store.snapshot(second, 180)["state"] == "stopped"
    finally:
        store.close()


def test_save_snapshot_requires_the_owning_installation() -> None:
    store = RelayStore()
    try:
        first = connected(
            store, "installation-one", "a" * 32, "profile-one", "CODEONE1", CHANNEL_ONE
        )
        # A second installation that knows another connection's id (e.g. from a
        # leaked payload) must not be able to write a snapshot for it.
        with pytest.raises(PermissionError):
            store.save_snapshot(
                first.id, "installation-two", "b" * 32, 1, {"state": "running"}
            )
        assert store.snapshot(first, 180) is None
        assert store.save_snapshot(
            first.id, "installation-one", "a" * 32, 1, {"state": "running"}
        )
        assert store.snapshot(first, 180)["state"] == "running"
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
        )
        store._db.execute(
            "UPDATE pairings SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", expired.id),
        )
        with pytest.raises(LookupError):
            store.claim_pairing("EXPIRED1", APP, GUILD, CHANNEL_ONE, USER_ONE)
        assert store.get_pairing(expired.id).status == "expired"

        connected_pairing = store.register_pairing(
            installation_id="installation-live",
            connector_secret="d" * 32,
            profile_id="profile-live",
            profile_name="Live",
            code="LIVEPAIR",
        )
        store.claim_pairing("LIVEPAIR", APP, GUILD, CHANNEL_NINE, USER_ONE)
        with pytest.raises(LookupError):
            store.claim_pairing("LIVEPAIR", APP, GUILD, CHANNEL_TEN, USER_TWO)
        assert store.get_pairing(connected_pairing.id).claimed_at is not None
    finally:
        store.close()


def test_pairing_rejects_active_channel_conflicts() -> None:
    store = RelayStore()
    try:
        connected(store, "installation-one", "a" * 32, "profile-one", "CHANNEL1", CHANNEL_ONE)
        store.register_pairing(
            installation_id="installation-two",
            connector_secret="b" * 32,
            profile_id="profile-two",
            profile_name="Two",
            code="CHANNEL2",
        )
        with pytest.raises(ValueError, match="already paired"):
            store.claim_pairing("CHANNEL2", APP, GUILD, CHANNEL_ONE, USER_TWO)
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
        claimed = store.claim_pairing("DUPLICATE1", APP, GUILD, CHANNEL_ONE, USER_ONE)
        with pytest.raises(LookupError):
            store.claim_pairing("DUPLICATE1", APP, GUILD, CHANNEL_ONE, USER_ONE)
        confirmed = store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        assert confirmed.channel_id == claimed.claimed_channel_id
    finally:
        store.close()


def test_connection_changes_require_the_connector_secret() -> None:
    store = RelayStore()
    try:
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "AUTHCHECK", CHANNEL_ONE
        )
        with pytest.raises(PermissionError):
            store.update_connection(
                connection.id, "installation-one", "b" * 32, publish_address=True
            )
        unchanged = store.connection(connection.id)
        assert unchanged is not None and unchanged.publish_address is False
        updated = store.update_connection(
            connection.id,
            "installation-one",
            "a" * 32,
            share_address=True,
            publish_address=True,
        )
        assert updated.publish_address is True
        assert updated.share_address is True
        assert store.save_snapshot(
            connection.id,
            "installation-one",
            "a" * 32,
            1,
            {
                "state": "online",
                "public": {
                    "state": "port_unverified",
                    "address": "203.0.113.10:25565",
                    "port": 25565,
                },
            },
        )
        updated = store.update_connection(
            connection.id, "installation-one", "a" * 32, share_address=False
        )
        assert updated.share_address is False
        assert updated.publish_address is False
        persisted = store.snapshot(updated, 180)
        assert persisted is not None
        assert persisted["public"] == {"state": "port_unverified"}
    finally:
        store.close()


def test_snapshot_staleness_uses_relay_receipt_time_not_host_heartbeat() -> None:
    store = RelayStore()
    try:
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "RECEIPT1", CHANNEL_ONE
        )
        assert store.save_snapshot(
            connection.id,
            "installation-one",
            "a" * 32,
            1,
            {"state": "running"},
        )
        stale_receipt = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        store._db.execute(
            "UPDATE latest_snapshots SET observed_at = ? WHERE connection_id = ?",
            (stale_receipt, connection.id),
        )

        assert store.heartbeat(connection.id, "installation-one", "a" * 32)
        refreshed = store.connection(connection.id)
        assert refreshed is not None
        snapshot = store.snapshot(refreshed, 60)
        assert snapshot is not None and snapshot["stale"] is True
        assert store.is_stale(refreshed, 60) is True
    finally:
        store.close()


def test_discord_revocation_rechecks_the_exact_binding_and_pairing_owner() -> None:
    store = RelayStore()
    try:
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "REVOKE01", CHANNEL_ONE
        )
        for application_id, guild_id, channel_id, owner_user_id in (
            ("1535816544951476325", GUILD, CHANNEL_ONE, connection.owner_user_id),
            (APP, "900000000000000099", CHANNEL_ONE, connection.owner_user_id),
            (APP, GUILD, CHANNEL_TWO, connection.owner_user_id),
            (APP, GUILD, CHANNEL_ONE, USER_TWO),
        ):
            with pytest.raises(LookupError):
                store.revoke_connection_for_discord(
                    connection.id,
                    application_id,
                    guild_id,
                    channel_id,
                    owner_user_id,
                )
            assert store.connection(connection.id) is not None

        revoked = store.revoke_connection_for_discord(
            connection.id,
            APP,
            GUILD,
            CHANNEL_ONE,
            connection.owner_user_id,
        )
        assert revoked.revoked_at is not None
        assert store.connection(connection.id) is None
        assert store.connection(connection.id, include_revoked=True) == revoked
    finally:
        store.close()


def test_pairing_confirmation_rechecks_expiry_and_snowflakes() -> None:
    store = RelayStore()
    try:
        with pytest.raises(ValueError, match="expiry"):
            store.register_pairing(
                installation_id="installation-one",
                connector_secret="a" * 32,
                profile_id="invalid-ttl",
                profile_name="Invalid",
                code="INVALID01",
                ttl_seconds=0,
            )
        pairing = store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="EXPIRE02",
        )
        with pytest.raises(ValueError, match="snowflake"):
            store.claim_pairing("EXPIRE02", APP, "guild-1", CHANNEL_ONE, USER_ONE)
        store.claim_pairing("EXPIRE02", APP, GUILD, CHANNEL_ONE, USER_ONE)
        store._db.execute(
            "UPDATE pairings SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", pairing.id),
        )
        with pytest.raises(LookupError):
            store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        expired = store.get_pairing(pairing.id)
        assert expired is not None and expired.status == "expired"
    finally:
        store.close()


def test_pairing_claim_roles_are_review_only_and_connection_starts_owner_only() -> None:
    store = RelayStore()
    try:
        owner = "123456789012345678"
        roles = ["987654321098765432", "987654321098765432"]
        pairing = store.register_pairing(
            installation_id="installation-one",
            connector_secret="a" * 32,
            profile_id="profile-one",
            profile_name="One",
            code="ROLEPAIR1",
        )
        claimed = store.claim_pairing(
            "ROLEPAIR1", APP, GUILD, CHANNEL_ONE, owner, roles
        )
        assert claimed.claimed_role_ids == (roles[0],)
        connection = store.confirm_pairing(pairing.id, "installation-one", "a" * 32)
        assert connection.authorized_user_ids == (owner,)
        assert connection.authorized_role_ids == ()
    finally:
        store.close()


def test_connection_principals_are_deduplicated_and_owner_cannot_be_removed() -> None:
    store = RelayStore()
    try:
        owner = "123456789012345678"
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "PRINCIPAL1", CHANNEL_ONE
        )
        with pytest.raises(ValueError, match="owner"):
            store.update_connection(
                connection.id,
                "installation-one",
                "a" * 32,
                authorized_user_ids=["987654321098765432"],
            )
        # Replace the fixture owner with a real snowflake for this contract
        # test, then verify deterministic deduplication.
        store._db.execute(
            "UPDATE connections SET owner_user_id = ?, authorized_user_ids = ? WHERE id = ?",
            (owner, f'["{owner}"]', connection.id),
        )
        updated = store.update_connection(
            connection.id,
            "installation-one",
            "a" * 32,
            authorized_user_ids=[owner, "987654321098765432", owner],
            authorized_role_ids=["111111111111111111", "111111111111111111"],
        )
        assert updated.authorized_user_ids == (owner, "987654321098765432")
        assert updated.authorized_role_ids == ("111111111111111111",)
    finally:
        store.close()


def test_rotation_keeps_old_secret_valid_until_new_secret_authenticates() -> None:
    store = RelayStore()
    try:
        store.register_installation("installation-one", "a" * 32)
        status = store.prepare_rotation("installation-one", "a" * 32, "b" * 32)
        assert status.pending is True
        assert store.authenticate("installation-one", "a" * 32) is True
        assert store.authenticate("installation-one", "b" * 32) is False
        assert store.authenticate_connector("installation-one", "b" * 32) is True
        assert store.authenticate("installation-one", "a" * 32) is False
        assert store.rotation_status("installation-one", "b" * 32).pending is False

        store.prepare_rotation("installation-one", "b" * 32, "c" * 32)
        store.cancel_rotation("installation-one", "b" * 32)
        assert store.authenticate("installation-one", "c" * 32) is False
        assert store.authenticate("installation-one", "b" * 32) is True
    finally:
        store.close()


def test_audits_and_delivery_are_safe_and_persisted() -> None:
    store = RelayStore()
    try:
        connection = connected(
            store, "installation-one", "a" * 32, "profile-one", "AUDIT001", CHANNEL_ONE
        )
        updated = store.record_delivery(connection.id, True, detail="token=secret")
        assert updated is not None
        assert updated.last_delivery_result == "delivered"
        assert updated.last_delivery_detail == "Status message delivered."
        audit = store.record_audit(
            installation_id=connection.installation_id,
            connection_id=connection.id,
            application_id=APP,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            command="pair",
            outcome="failed",
            safe_detail="PAIRCODE secret token",
        )
        assert "secret" not in audit.safe_detail.lower()
        assert store.audits(limit=1)[0].safe_detail == "Command failed safely."
    finally:
        store.close()


def test_existing_database_is_upgraded_idempotently(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE installations (
            id TEXT PRIMARY KEY, connector_secret_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE pairings (
            id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, profile_id TEXT NOT NULL,
            profile_name TEXT NOT NULL, code_hash TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL,
            status TEXT NOT NULL, claimed_application_id TEXT, claimed_guild_id TEXT,
            claimed_channel_id TEXT, claimed_user_id TEXT, claimed_at TEXT, confirmed_at TEXT);
        CREATE TABLE connections (
            id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, profile_id TEXT NOT NULL,
            profile_name TEXT NOT NULL, application_id TEXT NOT NULL, guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            publish_address INTEGER NOT NULL DEFAULT 0, status_message_id TEXT,
            last_sequence INTEGER NOT NULL DEFAULT 0,
            last_heartbeat_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (installation_id, profile_id),
            UNIQUE (application_id, guild_id, channel_id));
        INSERT INTO connections (
            id, installation_id, profile_id, profile_name, application_id, guild_id,
            channel_id, owner_user_id, enabled, publish_address, created_at, updated_at
        ) VALUES
            ('enabled', 'installation-one', 'profile-one', 'One',
             '1535816544951476324', '900000000000000001', '900000000000000002',
             '910000000000000001', 1, 1, '2026-01-01T00:00:00+00:00',
             '2026-01-01T00:00:00+00:00'),
            ('disabled', 'installation-one', 'profile-two', 'Two',
             '1535816544951476324', '900000000000000001', '900000000000000003',
             '910000000000000002', 0, 0, '2026-01-01T00:00:00+00:00',
             '2026-01-01T00:00:00+00:00');
        """
    )
    db.commit()
    db.close()
    first = RelayStore(path)
    first.close()
    second = RelayStore(path)
    try:
        columns = {
            str(row[1])
            for row in second._db.execute("PRAGMA table_info(connections)").fetchall()
        }
        assert {
            "authorized_user_ids",
            "authorized_role_ids",
            "last_delivery_result",
            "last_delivered_hash",
        } <= columns
        assert second._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'command_audits'"
        ).fetchone()
        audit_columns = {
            str(row[1])
            for row in second._db.execute("PRAGMA table_info(command_audits)").fetchall()
        }
        assert "profile_id" in audit_columns
        enabled = second.connection("enabled")
        disabled = second.connection("disabled")
        assert enabled is not None and enabled.share_address is True
        assert enabled.publish_address is True
        assert enabled.last_delivered_hash is None
        assert disabled is not None and disabled.enabled is False
        assert disabled.revoked_at is None
        indexes = {
            str(row[1])
            for row in second._db.execute("PRAGMA index_list(connections)").fetchall()
        }
        assert "uq_connections_active_profile" in indexes
        assert "uq_connections_active_channel" in indexes
    finally:
        second.close()


def test_legacy_connection_rebuild_rolls_back_atomically(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy-failure.db"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE connections (
            id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, profile_id TEXT NOT NULL,
            profile_name TEXT NOT NULL, application_id TEXT NOT NULL, guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            publish_address INTEGER NOT NULL DEFAULT 0, status_message_id TEXT,
            last_sequence INTEGER NOT NULL DEFAULT 0, last_heartbeat_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (installation_id, profile_id),
            UNIQUE (application_id, guild_id, channel_id));
        INSERT INTO connections (
            id, installation_id, profile_id, profile_name, application_id, guild_id,
            channel_id, owner_user_id, created_at, updated_at
        ) VALUES (
            'kept', 'installation-one', 'profile-one', 'One',
            '1535816544951476324', '900000000000000001', '900000000000000002',
            '910000000000000001', '2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00');
        """
    )
    db.close()

    original_connect = sqlite3.connect

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            if "ALTER TABLE connections_replacement RENAME TO connections" in sql:
                raise sqlite3.OperationalError("simulated migration interruption")
            return super().execute(sql, parameters)

    def failing_connect(*args, **kwargs):
        return original_connect(*args, factory=FailingConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", failing_connect)
    with pytest.raises(sqlite3.OperationalError, match="simulated migration"):
        RelayStore(path)

    check = original_connect(path)
    try:
        row = check.execute("SELECT id FROM connections").fetchone()
        assert row == ("kept",)
        assert check.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'connections_replacement'"
        ).fetchone() is None
    finally:
        check.close()
