from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_PRINCIPALS = 64
MAX_AUDIT_DETAIL = 160
MAX_AUDIT_COMMAND = 64
MAX_AUDIT_ROWS = 10_000
SNOWFLAKE_MIN_LENGTH = 17
SNOWFLAKE_MAX_LENGTH = 20


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_snowflake_ids(value: object, *, required: bool = False) -> tuple[str, ...]:
    """Return a bounded, deterministic set of Discord snowflake IDs."""

    if value is None:
        if required:
            raise ValueError("Discord principal IDs are required")
        return ()
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError("Discord principal IDs must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("Discord principal IDs must be strings")
        candidate = raw.strip()
        if (
            not candidate
            or not candidate.isdigit()
            or len(candidate) < SNOWFLAKE_MIN_LENGTH
            or len(candidate) > SNOWFLAKE_MAX_LENGTH
        ):
            raise ValueError("Discord principal IDs must be numeric snowflakes")
        if candidate not in seen:
            seen.add(candidate)
            result.append(candidate)
        if len(result) > MAX_PRINCIPALS:
            raise ValueError("Too many Discord principal IDs")
    return tuple(result)


def normalize_snowflake_id(value: object, label: str = "Discord ID") -> str:
    """Validate one Discord snowflake and return its normalized string form."""

    try:
        return normalize_snowflake_ids([value], required=True)[0]
    except (IndexError, ValueError) as exc:
        raise ValueError(f"{label} must be a numeric Discord snowflake") from exc


def _json_ids(value: object) -> str:
    return json.dumps(list(normalize_snowflake_ids(value)), separators=(",", ":"))


def _decode_ids(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        raw = json.loads(str(value))
    except (TypeError, ValueError):
        return ()
    try:
        return normalize_snowflake_ids(raw)
    except ValueError:
        return ()


@dataclass(frozen=True)
class Pairing:
    id: str
    installation_id: str
    profile_id: str
    profile_name: str
    expires_at: datetime
    status: str
    claimed_application_id: str | None = None
    claimed_guild_id: str | None = None
    claimed_channel_id: str | None = None
    claimed_user_id: str | None = None
    claimed_at: datetime | None = None
    confirmed_at: datetime | None = None
    claimed_role_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Connection:
    id: str
    installation_id: str
    profile_id: str
    profile_name: str
    application_id: str
    guild_id: str
    channel_id: str
    owner_user_id: str
    enabled: bool
    share_address: bool
    publish_address: bool
    status_message_id: str | None
    last_sequence: int
    last_heartbeat_at: datetime | None
    authorized_user_ids: tuple[str, ...] = ()
    authorized_role_ids: tuple[str, ...] = ()
    last_delivery_result: str | None = None
    last_delivery_at: datetime | None = None
    last_delivery_detail: str | None = None
    last_delivered_hash: str | None = None
    revoked_at: datetime | None = None


@dataclass(frozen=True)
class CommandAudit:
    id: str
    installation_id: str | None
    connection_id: str | None
    application_id: str | None
    guild_id: str | None
    channel_id: str | None
    user_id: str | None
    command: str
    outcome: str
    safe_detail: str
    created_at: datetime
    profile_id: str | None = None


@dataclass(frozen=True)
class RotationStatus:
    installation_id: str
    pending: bool
    expires_at: datetime | None


class RelayStore:
    """SQLite metadata store with one bounded latest snapshot per connection."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _initialize(self) -> None:
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS installations (
                    id TEXT PRIMARY KEY,
                    connector_secret_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    pending_connector_secret_hash TEXT,
                    pending_connector_secret_expires_at TEXT
                );
                CREATE TABLE IF NOT EXISTS pairings (
                    id TEXT PRIMARY KEY,
                    installation_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    code_hash TEXT NOT NULL UNIQUE,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    claimed_application_id TEXT,
                    claimed_guild_id TEXT,
                    claimed_channel_id TEXT,
                    claimed_user_id TEXT,
                    claimed_role_ids TEXT NOT NULL DEFAULT '[]',
                    claimed_at TEXT,
                    confirmed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_pairings_installation
                    ON pairings (installation_id);
                CREATE TABLE IF NOT EXISTS connections (
                    id TEXT PRIMARY KEY,
                    installation_id TEXT NOT NULL,
                    profile_id TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    authorized_user_ids TEXT NOT NULL DEFAULT '[]',
                    authorized_role_ids TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    share_address INTEGER NOT NULL DEFAULT 0,
                    publish_address INTEGER NOT NULL DEFAULT 0,
                    status_message_id TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    last_heartbeat_at TEXT,
                    last_delivery_result TEXT,
                    last_delivery_at TEXT,
                    last_delivery_detail TEXT,
                    last_delivered_hash TEXT,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS latest_snapshots (
                    connection_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS command_audits (
                    id TEXT PRIMARY KEY,
                    installation_id TEXT,
                    connection_id TEXT,
                    profile_id TEXT,
                    application_id TEXT,
                    guild_id TEXT,
                    channel_id TEXT,
                    user_id TEXT,
                    command TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    safe_detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_command_audits_created
                    ON command_audits (created_at);
                CREATE INDEX IF NOT EXISTS ix_command_audits_installation
                    ON command_audits (installation_id);
                """
            )
            self._ensure_columns(
                "installations",
                {
                    "pending_connector_secret_hash": "TEXT",
                    "pending_connector_secret_expires_at": "TEXT",
                },
            )
            self._ensure_columns("pairings", {"claimed_role_ids": "TEXT NOT NULL DEFAULT '[]'"})
            self._ensure_columns(
                "connections",
                {
                    "authorized_user_ids": "TEXT NOT NULL DEFAULT '[]'",
                    "authorized_role_ids": "TEXT NOT NULL DEFAULT '[]'",
                    "share_address": "INTEGER NOT NULL DEFAULT 0",
                    "last_delivery_result": "TEXT",
                    "last_delivery_at": "TEXT",
                    "last_delivery_detail": "TEXT",
                    "last_delivered_hash": "TEXT",
                    "revoked_at": "TEXT",
                },
            )
            # Legacy deployments used publish_address as the only address
            # consent bit. Preserve that explicit opt-in while splitting the
            # narrower ephemeral and persistent permissions.
            self._db.execute(
                "UPDATE connections SET share_address = 1 WHERE publish_address = 1"
            )
            # Legacy enabled=0 rows are intentionally retained as reversible
            # disabled connections. The old schema could not distinguish a
            # disable from a revoke, so silently tombstoning them would destroy
            # the safer reversible interpretation. Owners can terminally revoke
            # them through the hardened control path after upgrade.
            self._rebuild_connections_for_partial_uniqueness()
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS ix_connections_installation "
                "ON connections (installation_id)"
            )
            self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_connections_active_profile "
                "ON connections (installation_id, profile_id) WHERE revoked_at IS NULL"
            )
            self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_connections_active_channel "
                "ON connections (application_id, guild_id, channel_id) "
                "WHERE revoked_at IS NULL"
            )
            self._ensure_columns("command_audits", {"profile_id": "TEXT"})
            self._db.execute(
                "DELETE FROM command_audits WHERE id IN ("
                "SELECT id FROM command_audits ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (MAX_AUDIT_ROWS,),
            )

    def _rebuild_connections_for_partial_uniqueness(self) -> None:
        """Replace legacy table-level uniqueness with active-row partial indexes."""

        row = self._db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'connections'"
        ).fetchone()
        table_sql = str(row["sql"] or "") if row is not None else ""
        compact = "".join(table_sql.lower().split())
        if "unique(installation_id,profile_id)" not in compact and (
            "unique(application_id,guild_id,channel_id)" not in compact
        ):
            return
        try:
            self._db.execute("SAVEPOINT rebuild_connections")
            self._db.execute("DROP TABLE IF EXISTS connections_replacement")
            self._db.execute(
                """
                CREATE TABLE connections_replacement (
                id TEXT PRIMARY KEY,
                installation_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                profile_name TEXT NOT NULL,
                application_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                authorized_user_ids TEXT NOT NULL DEFAULT '[]',
                authorized_role_ids TEXT NOT NULL DEFAULT '[]',
                enabled INTEGER NOT NULL DEFAULT 1,
                share_address INTEGER NOT NULL DEFAULT 0,
                publish_address INTEGER NOT NULL DEFAULT 0,
                status_message_id TEXT,
                last_sequence INTEGER NOT NULL DEFAULT 0,
                last_heartbeat_at TEXT,
                last_delivery_result TEXT,
                last_delivery_at TEXT,
                last_delivery_detail TEXT,
                last_delivered_hash TEXT,
                revoked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
                )
                """
            )
            self._db.execute(
                """
                INSERT INTO connections_replacement (
                id, installation_id, profile_id, profile_name, application_id,
                guild_id, channel_id, owner_user_id, authorized_user_ids,
                authorized_role_ids, enabled, share_address, publish_address,
                status_message_id, last_sequence, last_heartbeat_at,
                last_delivery_result, last_delivery_at, last_delivery_detail,
                last_delivered_hash, revoked_at, created_at, updated_at
                )
                SELECT
                id, installation_id, profile_id, profile_name, application_id,
                guild_id, channel_id, owner_user_id, authorized_user_ids,
                authorized_role_ids, enabled, share_address, publish_address,
                status_message_id, last_sequence, last_heartbeat_at,
                last_delivery_result, last_delivery_at, last_delivery_detail,
                last_delivered_hash, revoked_at, created_at, updated_at
                FROM connections
                """
            )
            self._db.execute("ALTER TABLE connections RENAME TO connections_legacy_unique")
            self._db.execute("ALTER TABLE connections_replacement RENAME TO connections")
            self._db.execute("DROP TABLE connections_legacy_unique")
            self._db.execute("RELEASE SAVEPOINT rebuild_connections")
        except Exception:
            self._db.execute("ROLLBACK TO SAVEPOINT rebuild_connections")
            self._db.execute("RELEASE SAVEPOINT rebuild_connections")
            raise

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        existing = {
            str(row[1]) for row in self._db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def _pairing(self, row: sqlite3.Row) -> Pairing:
        return Pairing(
            id=row["id"],
            installation_id=row["installation_id"],
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            expires_at=self._dt(row["expires_at"]) or utcnow(),
            status=row["status"],
            claimed_application_id=row["claimed_application_id"],
            claimed_guild_id=row["claimed_guild_id"],
            claimed_channel_id=row["claimed_channel_id"],
            claimed_user_id=row["claimed_user_id"],
            claimed_role_ids=_decode_ids(row["claimed_role_ids"]),
            claimed_at=self._dt(row["claimed_at"]),
            confirmed_at=self._dt(row["confirmed_at"]),
        )

    def _connection(self, row: sqlite3.Row) -> Connection:
        owner = str(row["owner_user_id"])
        users = _decode_ids(row["authorized_user_ids"])
        if owner and owner not in users:
            users = (owner, *users)
        return Connection(
            id=row["id"],
            installation_id=row["installation_id"],
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            application_id=row["application_id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            owner_user_id=owner,
            enabled=bool(row["enabled"]),
            share_address=bool(row["share_address"]),
            publish_address=bool(row["publish_address"]),
            status_message_id=row["status_message_id"],
            last_sequence=int(row["last_sequence"]),
            last_heartbeat_at=self._dt(row["last_heartbeat_at"]),
            authorized_user_ids=users,
            authorized_role_ids=_decode_ids(row["authorized_role_ids"]),
            last_delivery_result=row["last_delivery_result"],
            last_delivery_at=self._dt(row["last_delivery_at"]),
            last_delivery_detail=row["last_delivery_detail"],
            last_delivered_hash=row["last_delivered_hash"],
            revoked_at=self._dt(row["revoked_at"]),
        )

    def _expire_pending_rotation_locked(self, installation_id: str | None = None) -> None:
        now = utcnow().isoformat()
        if installation_id is None:
            self._db.execute(
                "UPDATE installations SET pending_connector_secret_hash = NULL, "
                "pending_connector_secret_expires_at = NULL "
                "WHERE pending_connector_secret_expires_at IS NOT NULL "
                "AND pending_connector_secret_expires_at <= ?",
                (now,),
            )
        else:
            self._db.execute(
                "UPDATE installations SET pending_connector_secret_hash = NULL, "
                "pending_connector_secret_expires_at = NULL "
                "WHERE id = ? AND pending_connector_secret_expires_at IS NOT NULL "
                "AND pending_connector_secret_expires_at <= ?",
                (installation_id, now),
            )

    def _check_current_installation(self, installation_id: str, connector_secret: str) -> None:
        """Authenticate only the committed connector credential."""

        self._expire_pending_rotation_locked(installation_id)
        row = self._db.execute(
            "SELECT connector_secret_hash FROM installations WHERE id = ?",
            (installation_id,),
        ).fetchone()
        if row is None or not secrets.compare_digest(
            row["connector_secret_hash"], digest(connector_secret)
        ):
            raise PermissionError("invalid relay connector credentials")

    def _check_connector_installation(self, installation_id: str, connector_secret: str) -> None:
        """Authenticate a WebSocket connector and promote a valid pending secret."""

        self._expire_pending_rotation_locked(installation_id)
        row = self._db.execute(
            "SELECT connector_secret_hash, pending_connector_secret_hash "
            "FROM installations WHERE id = ?",
            (installation_id,),
        ).fetchone()
        if row is None:
            raise PermissionError("invalid relay connector credentials")
        candidate = digest(connector_secret)
        if secrets.compare_digest(row["connector_secret_hash"], candidate):
            return
        pending = row["pending_connector_secret_hash"]
        if pending and secrets.compare_digest(pending, candidate):
            self._db.execute(
                "UPDATE installations SET connector_secret_hash = pending_connector_secret_hash, "
                "pending_connector_secret_hash = NULL, pending_connector_secret_expires_at = NULL "
                "WHERE id = ?",
                (installation_id,),
            )
            return
        raise PermissionError("invalid relay connector credentials")

    def register_installation(self, installation_id: str, connector_secret: str) -> None:
        """Register a host before its first pairing so it can stay idle-connected."""

        if not installation_id or not connector_secret:
            raise ValueError("installation registration is incomplete")
        now = utcnow()
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT 1 FROM installations WHERE id = ?", (installation_id,)
            ).fetchone()
            if row is not None:
                self._check_current_installation(installation_id, connector_secret)
                return
            self._db.execute(
                "INSERT INTO installations "
                "(id, connector_secret_hash, created_at) VALUES (?, ?, ?)",
                (installation_id, digest(connector_secret), now.isoformat()),
            )

    def register_pairing(
        self,
        *,
        installation_id: str,
        connector_secret: str,
        profile_id: str,
        profile_name: str,
        code: str,
        ttl_seconds: int = 600,
    ) -> Pairing:
        if not installation_id or not connector_secret or not profile_id or not code:
            raise ValueError("pairing registration is incomplete")
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds < 1
            or ttl_seconds > 3_600
        ):
            raise ValueError("pairing expiry is out of bounds")
        now = utcnow()
        pairing = Pairing(
            id=str(uuid4()),
            installation_id=installation_id,
            profile_id=profile_id,
            profile_name=profile_name[:80],
            expires_at=now + timedelta(seconds=ttl_seconds),
            status="pending",
        )
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT 1 FROM installations WHERE id = ?", (installation_id,)
            ).fetchone()
            if row is not None:
                self._check_current_installation(installation_id, connector_secret)
            else:
                self._db.execute(
                    "INSERT INTO installations "
                    "(id, connector_secret_hash, created_at) VALUES (?, ?, ?)",
                    (installation_id, digest(connector_secret), now.isoformat()),
                )
            active_connection = self._db.execute(
                "SELECT 1 FROM connections WHERE installation_id = ? AND profile_id = ? "
                "AND revoked_at IS NULL",
                (installation_id, profile_id),
            ).fetchone()
            if active_connection is not None:
                raise ValueError("profile is already paired")
            self._db.execute(
                "UPDATE pairings SET status = 'replaced' WHERE installation_id = ? "
                "AND profile_id = ? AND status = 'pending'",
                (installation_id, profile_id),
            )
            self._db.execute(
                "INSERT INTO pairings (id, installation_id, profile_id, profile_name, "
                "code_hash, expires_at, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                (
                    pairing.id,
                    installation_id,
                    profile_id,
                    pairing.profile_name,
                    digest(code),
                    pairing.expires_at.isoformat(),
                ),
            )
        return pairing

    def authenticate(self, installation_id: str, connector_secret: str) -> bool:
        with self._lock, self._db:
            try:
                self._check_current_installation(installation_id, connector_secret)
            except PermissionError:
                return False
            return True

    def authenticate_connector(self, installation_id: str, connector_secret: str) -> bool:
        """Authenticate a host socket; this is the sole pending-secret promotion path."""

        with self._lock, self._db:
            try:
                self._check_connector_installation(installation_id, connector_secret)
            except PermissionError:
                return False
            return True

    def claim_pairing(
        self,
        code: str,
        application_id: str,
        guild_id: str,
        channel_id: str,
        user_id: str,
        role_ids: object = (),
    ) -> Pairing:
        application_id = normalize_snowflake_id(application_id, "application ID")
        guild_id = normalize_snowflake_id(guild_id, "guild ID")
        channel_id = normalize_snowflake_id(channel_id, "channel ID")
        user_id = normalize_snowflake_id(user_id, "user ID")
        claimed_roles = normalize_snowflake_ids(role_ids)
        now = utcnow()
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT * FROM pairings WHERE code_hash = ? AND status = 'pending'",
                (digest(code),),
            ).fetchone()
            if row is None:
                raise LookupError("pairing code is invalid or expired")
            if row["claimed_at"] is not None:
                raise LookupError("pairing code is invalid or expired")
            expires_at = self._dt(row["expires_at"])
            if expires_at is None or expires_at <= now:
                self._db.execute(
                    "UPDATE pairings SET status = 'expired' WHERE id = ?", (row["id"],)
                )
                self._db.commit()
                raise LookupError("pairing code is invalid or expired")
            conflict = self._db.execute(
                "SELECT 1 FROM connections WHERE application_id = ? AND guild_id = ? "
                "AND channel_id = ? AND revoked_at IS NULL",
                (application_id, guild_id, channel_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError("channel is already paired")
            claimed_at = now.isoformat()
            self._db.execute(
                "UPDATE pairings SET claimed_application_id = ?, claimed_guild_id = ?, "
                "claimed_channel_id = ?, claimed_user_id = ?, claimed_role_ids = ?, "
                "claimed_at = ? WHERE id = ?",
                (
                    application_id,
                    guild_id,
                    channel_id,
                    user_id,
                    json.dumps(list(claimed_roles), separators=(",", ":")),
                    claimed_at,
                    row["id"],
                ),
            )
            updated = self._db.execute(
                "SELECT * FROM pairings WHERE id = ?", (row["id"],)
            ).fetchone()
            assert updated is not None
            return self._pairing(updated)

    def pending_for_installation(self, installation_id: str) -> list[Pairing]:
        with self._lock, self._db:
            now = utcnow().isoformat()
            self._db.execute(
                "UPDATE pairings SET status = 'expired' WHERE installation_id = ? "
                "AND status = 'pending' AND expires_at <= ?",
                (installation_id, now),
            )
            rows = self._db.execute(
                "SELECT * FROM pairings WHERE installation_id = ? AND status = 'pending' "
                "AND claimed_at IS NOT NULL AND expires_at > ?",
                (installation_id, now),
            ).fetchall()
            return [self._pairing(row) for row in rows]

    def get_pairing(self, pairing_id: str) -> Pairing | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM pairings WHERE id = ?", (pairing_id,)).fetchone()
            return self._pairing(row) if row else None

    def confirm_pairing(
        self, pairing_id: str, installation_id: str, connector_secret: str
    ) -> Connection:
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT * FROM pairings WHERE id = ? AND installation_id = ? "
                "AND status = 'pending'",
                (pairing_id, installation_id),
            ).fetchone()
            if row is None or row["claimed_at"] is None:
                raise LookupError("pairing is not awaiting confirmation")
            expires_at = self._dt(row["expires_at"])
            if expires_at is None or expires_at <= utcnow():
                if row is not None:
                    self._db.execute(
                        "UPDATE pairings SET status = 'expired' WHERE id = ?", (pairing_id,)
                    )
                    self._db.commit()
                raise LookupError("pairing is not awaiting confirmation")
            conflict = self._db.execute(
                "SELECT 1 FROM connections WHERE application_id = ? AND guild_id = ? "
                "AND channel_id = ? AND revoked_at IS NULL",
                (row["claimed_application_id"], row["claimed_guild_id"], row["claimed_channel_id"]),
            ).fetchone()
            if conflict is not None:
                raise ValueError("channel is already paired")
            profile_conflict = self._db.execute(
                "SELECT 1 FROM connections WHERE installation_id = ? AND profile_id = ? "
                "AND revoked_at IS NULL",
                (installation_id, row["profile_id"]),
            ).fetchone()
            if profile_conflict is not None:
                raise ValueError("profile is already paired")
            now = utcnow()
            connection_id = str(uuid4())
            owner = str(row["claimed_user_id"])
            owner_ids = json.dumps([owner], separators=(",", ":"))
            self._db.execute(
                "INSERT INTO connections (id, installation_id, profile_id, profile_name, "
                "application_id, guild_id, channel_id, owner_user_id, authorized_user_ids, "
                "authorized_role_ids, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
                (
                    connection_id,
                    row["installation_id"],
                    row["profile_id"],
                    row["profile_name"],
                    row["claimed_application_id"],
                    row["claimed_guild_id"],
                    row["claimed_channel_id"],
                    owner,
                    owner_ids,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._db.execute(
                "UPDATE pairings SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
                (now.isoformat(), pairing_id),
            )
            created = self._db.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
            assert created is not None
            return self._connection(created)

    def connection_for_discord(
        self, application_id: str, guild_id: str, channel_id: str
    ) -> Connection | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM connections WHERE application_id = ? AND guild_id = ? "
                "AND channel_id = ? AND enabled = 1 AND revoked_at IS NULL",
                (application_id, guild_id, channel_id),
            ).fetchone()
            return self._connection(row) if row else None

    def connection(self, connection_id: str, *, include_revoked: bool = False) -> Connection | None:
        with self._lock:
            query = "SELECT * FROM connections WHERE id = ?"
            if not include_revoked:
                query += " AND revoked_at IS NULL"
            row = self._db.execute(query, (connection_id,)).fetchone()
            return self._connection(row) if row else None

    def connections_for_installation(self, installation_id: str) -> list[Connection]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM connections WHERE installation_id = ? AND revoked_at IS NULL "
                "ORDER BY created_at",
                (installation_id,),
            ).fetchall()
            return [self._connection(row) for row in rows]

    def revocations_for_installation(self, installation_id: str) -> list[Connection]:
        """Return retained terminal tombstones for reconnect reconciliation."""

        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM connections WHERE installation_id = ? AND revoked_at IS NOT NULL "
                "ORDER BY revoked_at, created_at",
                (installation_id,),
            ).fetchall()
            return [self._connection(row) for row in rows]

    def active_connections(self) -> list[Connection]:
        """Return every non-revoked binding for background reconciliation."""

        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM connections WHERE revoked_at IS NULL ORDER BY created_at"
            ).fetchall()
            return [self._connection(row) for row in rows]

    def update_connection(
        self,
        connection_id: str,
        installation_id: str,
        connector_secret: str,
        **changes: object,
    ) -> Connection:
        allowed = {
            "enabled",
            "share_address",
            "publish_address",
            "authorized_user_ids",
            "authorized_role_ids",
        }
        if set(changes) - allowed:
            raise ValueError("unsupported connection change")
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT * FROM connections WHERE id = ? AND installation_id = ? "
                "AND revoked_at IS NULL",
                (connection_id, installation_id),
            ).fetchone()
            if row is None:
                raise LookupError("connection not found")
            values: dict[str, object] = {}
            for key, value in changes.items():
                if value is None:
                    continue
                if key in {"authorized_user_ids", "authorized_role_ids"}:
                    values[key] = _json_ids(value)
                elif key in {"enabled", "share_address", "publish_address"}:
                    values[key] = int(bool(value))
            if values.get("share_address") == 0:
                if values.get("publish_address") == 1:
                    raise ValueError(
                        "persistent address publication requires address sharing"
                    )
                values["publish_address"] = 0
            resulting_share = bool(values.get("share_address", row["share_address"]))
            resulting_publish = bool(values.get("publish_address", row["publish_address"]))
            if resulting_publish and not resulting_share:
                raise ValueError("persistent address publication requires address sharing")
            if "authorized_user_ids" in values:
                ids = _decode_ids(values["authorized_user_ids"])
                owner = str(row["owner_user_id"])
                if owner not in ids:
                    raise ValueError("the pairing owner must remain authorized")
            if values:
                assignments = ", ".join(f"{key} = ?" for key in values)
                self._db.execute(  # noqa: S608 - assignments are allow-listed above
                    f"UPDATE connections SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608
                    (*values.values(), utcnow().isoformat(), connection_id),
                )
            if values.get("share_address") == 0:
                self._scrub_snapshot_address_locked(connection_id)
            updated = self._db.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
            assert updated is not None
            return self._connection(updated)

    def _scrub_snapshot_address_locked(self, connection_id: str) -> None:
        row = self._db.execute(
            "SELECT payload_json FROM latest_snapshots WHERE connection_id = ?",
            (connection_id,),
        ).fetchone()
        if row is None:
            return
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError):
            self._db.execute(
                "DELETE FROM latest_snapshots WHERE connection_id = ?", (connection_id,)
            )
            return
        if not isinstance(payload, dict):
            self._db.execute(
                "DELETE FROM latest_snapshots WHERE connection_id = ?", (connection_id,)
            )
            return
        public = payload.get("public")
        if isinstance(public, dict):
            sanitized_public = dict(public)
            sanitized_public.pop("address", None)
            sanitized_public.pop("port", None)
            payload["public"] = sanitized_public
        self._db.execute(
            "UPDATE latest_snapshots SET payload_json = ? WHERE connection_id = ?",
            (json.dumps(payload, separators=(",", ":"), sort_keys=True), connection_id),
        )

    def _terminal_revoke_locked(
        self, connection_id: str, installation_id: str
    ) -> Connection | None:
        now = utcnow().isoformat()
        changed = self._db.execute(
            "UPDATE connections SET enabled = 0, revoked_at = ?, updated_at = ? "
            "WHERE id = ? AND installation_id = ? AND revoked_at IS NULL",
            (now, now, connection_id, installation_id),
        ).rowcount
        if not changed:
            return None
        self._db.execute("DELETE FROM latest_snapshots WHERE connection_id = ?", (connection_id,))
        row = self._db.execute(
            "SELECT * FROM connections WHERE id = ?", (connection_id,)
        ).fetchone()
        return self._connection(row) if row else None

    def revoke_connection(
        self, connection_id: str, installation_id: str, connector_secret: str
    ) -> Connection:
        """Terminally revoke through the authenticated host control plane."""

        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            revoked = self._terminal_revoke_locked(connection_id, installation_id)
            if revoked is None:
                raise LookupError("connection not found")
            return revoked

    def revoke_connection_for_discord(
        self,
        connection_id: str,
        application_id: str,
        guild_id: str,
        channel_id: str,
        owner_user_id: str,
    ) -> Connection:
        """Terminally revoke after exact Discord owner authorization."""

        application_id = normalize_snowflake_id(application_id, "application ID")
        guild_id = normalize_snowflake_id(guild_id, "guild ID")
        channel_id = normalize_snowflake_id(channel_id, "channel ID")
        owner_user_id = normalize_snowflake_id(owner_user_id, "owner user ID")
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT installation_id FROM connections WHERE id = ? "
                "AND application_id = ? AND guild_id = ? AND channel_id = ? "
                "AND owner_user_id = ? AND revoked_at IS NULL",
                (
                    connection_id,
                    application_id,
                    guild_id,
                    channel_id,
                    owner_user_id,
                ),
            ).fetchone()
            if row is None:
                raise LookupError("connection not found")
            revoked = self._terminal_revoke_locked(connection_id, str(row["installation_id"]))
            assert revoked is not None
            return revoked

    def save_snapshot(
        self,
        connection_id: str,
        installation_id: str,
        connector_secret: str,
        sequence: int,
        snapshot: dict[str, Any],
    ) -> bool:
        if (
            not isinstance(sequence, int)
            or isinstance(sequence, bool)
            or sequence < 1
            or sequence > 9_223_372_036_854_775_807
        ):
            return False
        try:
            encoded = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            return False
        if len(encoded.encode("utf-8")) > 8_192:
            return False
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT last_sequence FROM connections WHERE id = ? AND installation_id = ? "
                "AND enabled = 1 AND revoked_at IS NULL",
                (connection_id, installation_id),
            ).fetchone()
            if row is None or sequence <= int(row["last_sequence"]):
                return False
            now = utcnow().isoformat()
            self._db.execute(
                "UPDATE connections SET last_sequence = ?, last_heartbeat_at = ?, "
                "updated_at = ? WHERE id = ?",
                (sequence, now, now, connection_id),
            )
            self._db.execute(
                "INSERT INTO latest_snapshots "
                "(connection_id, sequence, observed_at, payload_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(connection_id) DO UPDATE SET sequence = excluded.sequence, "
                "observed_at = excluded.observed_at, payload_json = excluded.payload_json",
                (connection_id, sequence, now, encoded),
            )
            return True

    def heartbeat(
        self, connection_id: str, installation_id: str, connector_secret: str
    ) -> bool:
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            now = utcnow().isoformat()
            changed = self._db.execute(
                "UPDATE connections SET last_heartbeat_at = ?, updated_at = ? WHERE id = ? "
                "AND installation_id = ? AND enabled = 1 AND revoked_at IS NULL",
                (now, now, connection_id, installation_id),
            ).rowcount
            return bool(changed)

    def snapshot(self, connection: Connection, stale_after_seconds: int) -> dict[str, Any] | None:
        if connection.revoked_at is not None:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT sequence, observed_at, payload_json FROM latest_snapshots "
                "WHERE connection_id = ?",
                (connection.id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(str(row["payload_json"]))
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        snapshot = {
            "sequence": int(row["sequence"]),
            "observed_at": str(row["observed_at"]),
            **payload,
        }
        received_at = self._dt(str(row["observed_at"]))
        snapshot["stale"] = (
            received_at is None
            or (utcnow() - received_at).total_seconds() > stale_after_seconds
        )
        return snapshot

    def is_stale(self, connection: Connection, stale_after_seconds: int) -> bool:
        if connection.revoked_at is not None:
            return False
        with self._lock:
            row = self._db.execute(
                "SELECT observed_at FROM latest_snapshots WHERE connection_id = ?",
                (connection.id,),
            ).fetchone()
        if row is None:
            return False
        received_at = self._dt(str(row["observed_at"]))
        return received_at is None or (
            utcnow() - received_at
        ).total_seconds() > stale_after_seconds

    def set_status_message(self, connection_id: str, message_id: str) -> None:
        message_id = normalize_snowflake_id(message_id, "status message ID")
        with self._lock, self._db:
            self._db.execute(
                "UPDATE connections SET status_message_id = ?, updated_at = ? WHERE id = ? "
                "AND revoked_at IS NULL",
                (message_id, utcnow().isoformat(), connection_id),
            )

    def record_delivery(
        self,
        connection_id: str,
        delivered: bool,
        *,
        detail: str | None = None,
        desired_hash: str | None = None,
    ) -> Connection | None:
        if desired_hash is not None and (
            len(desired_hash) != 64
            or any(character not in "0123456789abcdef" for character in desired_hash)
        ):
            raise ValueError("delivery content hash is invalid")
        result = "delivered" if delivered else "failed"
        safe_detail = detail or (
            "Status message delivered." if delivered else "Status message delivery failed."
        )
        if safe_detail not in {
            "Status message delivered.",
            "Status message delivery failed.",
        }:
            safe_detail = (
                "Status message delivered."
                if delivered
                else "Status message delivery failed."
            )
        with self._lock, self._db:
            now = utcnow().isoformat()
            self._db.execute(
                "UPDATE connections SET last_delivery_result = ?, last_delivery_at = ?, "
                "last_delivery_detail = ?, last_delivered_hash = CASE "
                "WHEN ? = 1 AND ? IS NOT NULL THEN ? ELSE last_delivered_hash END, "
                "updated_at = ? WHERE id = ?",
                (
                    result,
                    now,
                    safe_detail,
                    int(delivered),
                    desired_hash,
                    desired_hash,
                    now,
                    connection_id,
                ),
            )
            row = self._db.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
            return self._connection(row) if row else None

    def record_audit(
        self,
        *,
        installation_id: str | None,
        connection_id: str | None,
        profile_id: str | None = None,
        application_id: str | None,
        guild_id: str | None,
        channel_id: str | None,
        user_id: str | None,
        command: str,
        outcome: str,
        safe_detail: str,
    ) -> CommandAudit:
        allowed_outcomes = {"accepted", "denied", "failed", "rate_limited"}
        if outcome not in allowed_outcomes:
            raise ValueError("unsupported command audit outcome")
        safe_details = {
            "accepted": "Command accepted.",
            "denied": "Command denied.",
            "failed": "Command failed safely.",
            "rate_limited": "Command rate limited.",
        }
        audit = CommandAudit(
            id=str(uuid4()),
            installation_id=installation_id,
            connection_id=connection_id,
            profile_id=profile_id,
            application_id=application_id,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=user_id,
            command=command[:MAX_AUDIT_COMMAND],
            outcome=outcome,
            # The caller supplies a descriptive label for readability, but
            # the persisted value is always one of these fixed safe strings.
            safe_detail=safe_details[outcome],
            created_at=utcnow(),
        )
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO command_audits (id, installation_id, connection_id, profile_id, "
                "application_id, guild_id, channel_id, user_id, command, outcome, "
                "safe_detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit.id,
                    audit.installation_id,
                    audit.connection_id,
                    audit.profile_id,
                    audit.application_id,
                    audit.guild_id,
                    audit.channel_id,
                    audit.user_id,
                    audit.command,
                    audit.outcome,
                    audit.safe_detail,
                    audit.created_at.isoformat(),
                ),
            )
            self._db.execute(
                "DELETE FROM command_audits WHERE id IN ("
                "SELECT id FROM command_audits ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                (MAX_AUDIT_ROWS,),
            )
        return audit

    def audits(self, *, limit: int = 100) -> list[CommandAudit]:
        bounded_limit = max(1, min(int(limit), MAX_AUDIT_ROWS))
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM command_audits ORDER BY created_at DESC LIMIT ?", (bounded_limit,)
            ).fetchall()
            return [
                CommandAudit(
                    id=row["id"],
                    installation_id=row["installation_id"],
                    connection_id=row["connection_id"],
                    profile_id=row["profile_id"],
                    application_id=row["application_id"],
                    guild_id=row["guild_id"],
                    channel_id=row["channel_id"],
                    user_id=row["user_id"],
                    command=row["command"],
                    outcome=row["outcome"],
                    safe_detail=row["safe_detail"],
                    created_at=self._dt(row["created_at"]) or utcnow(),
                )
                for row in rows
            ]

    def prepare_rotation(
        self,
        installation_id: str,
        connector_secret: str,
        replacement_secret: str,
        *,
        ttl_seconds: int = 600,
    ) -> RotationStatus:
        if (
            not isinstance(replacement_secret, str)
            or not replacement_secret
            or len(replacement_secret) < 32
            or len(replacement_secret) > 256
        ):
            raise ValueError("replacement connector credentials are invalid")
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or ttl_seconds < 1
            or ttl_seconds > 86_400
        ):
            raise ValueError("rotation expiry is out of bounds")
        expires = utcnow() + timedelta(seconds=ttl_seconds)
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT connector_secret_hash FROM installations WHERE id = ?",
                (installation_id,),
            ).fetchone()
            if row is None or secrets.compare_digest(
                row["connector_secret_hash"], digest(replacement_secret)
            ):
                raise ValueError("replacement connector credentials must differ")
            self._db.execute(
                "UPDATE installations SET pending_connector_secret_hash = ?, "
                "pending_connector_secret_expires_at = ? WHERE id = ?",
                (digest(replacement_secret), expires.isoformat(), installation_id),
            )
        return RotationStatus(installation_id, True, expires)

    def cancel_rotation(self, installation_id: str, connector_secret: str) -> RotationStatus:
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            self._db.execute(
                "UPDATE installations SET pending_connector_secret_hash = NULL, "
                "pending_connector_secret_expires_at = NULL WHERE id = ?",
                (installation_id,),
            )
        return RotationStatus(installation_id, False, None)

    def rotation_status(self, installation_id: str, connector_secret: str) -> RotationStatus:
        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT pending_connector_secret_expires_at FROM installations WHERE id = ?",
                (installation_id,),
            ).fetchone()
            expires = self._dt(row["pending_connector_secret_expires_at"]) if row else None
            return RotationStatus(installation_id, expires is not None, expires)

    def revoke_missing_profile_binding(
        self, connection_id: str, installation_id: str, connector_secret: str
    ) -> bool:
        """Terminally revoke a missing profile reported by its authenticated host."""

        with self._lock, self._db:
            self._check_current_installation(installation_id, connector_secret)
            return self._terminal_revoke_locked(connection_id, installation_id) is not None
