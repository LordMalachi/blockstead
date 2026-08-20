from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    publish_address: bool
    status_message_id: str | None
    last_sequence: int
    last_heartbeat_at: datetime | None


class RelayStore:
    """Small SQLite-backed metadata store; snapshots stay in memory only."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._snapshots: dict[str, dict[str, Any]] = {}
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
                    created_at TEXT NOT NULL
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
                    enabled INTEGER NOT NULL DEFAULT 1,
                    publish_address INTEGER NOT NULL DEFAULT 0,
                    status_message_id TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    last_heartbeat_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (installation_id, profile_id),
                    UNIQUE (application_id, guild_id, channel_id)
                );
                CREATE INDEX IF NOT EXISTS ix_connections_installation
                    ON connections (installation_id);
                """
            )

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
            claimed_at=self._dt(row["claimed_at"]),
            confirmed_at=self._dt(row["confirmed_at"]),
        )

    def _connection(self, row: sqlite3.Row) -> Connection:
        return Connection(
            id=row["id"],
            installation_id=row["installation_id"],
            profile_id=row["profile_id"],
            profile_name=row["profile_name"],
            application_id=row["application_id"],
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            owner_user_id=row["owner_user_id"],
            enabled=bool(row["enabled"]),
            publish_address=bool(row["publish_address"]),
            status_message_id=row["status_message_id"],
            last_sequence=int(row["last_sequence"]),
            last_heartbeat_at=self._dt(row["last_heartbeat_at"]),
        )

    def _check_installation(self, installation_id: str, connector_secret: str) -> None:
        row = self._db.execute(
            "SELECT connector_secret_hash FROM installations WHERE id = ?", (installation_id,)
        ).fetchone()
        if row is not None and not secrets.compare_digest(
            row["connector_secret_hash"], digest(connector_secret)
        ):
            raise PermissionError("invalid relay connector credentials")

    def register_installation(self, installation_id: str, connector_secret: str) -> None:
        """Register a host before its first pairing so it can stay idle-connected."""

        if not installation_id or not connector_secret:
            raise ValueError("installation registration is incomplete")
        now = utcnow()
        with self._lock, self._db:
            self._check_installation(installation_id, connector_secret)
            self._db.execute(
                "INSERT OR IGNORE INTO installations "
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
            self._check_installation(installation_id, connector_secret)
            self._db.execute(
                "INSERT OR IGNORE INTO installations "
                "(id, connector_secret_hash, created_at) VALUES (?, ?, ?)",
                (installation_id, digest(connector_secret), now.isoformat()),
            )
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
        with self._lock:
            try:
                self._check_installation(installation_id, connector_secret)
            except PermissionError:
                return False
            return (
                self._db.execute(
                    "SELECT 1 FROM installations WHERE id = ?", (installation_id,)
                ).fetchone()
                is not None
            )

    def claim_pairing(
        self, code: str, application_id: str, guild_id: str, channel_id: str, user_id: str
    ) -> Pairing:
        now = utcnow()
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT * FROM pairings WHERE code_hash = ? AND status = 'pending'",
                (digest(code),),
            ).fetchone()
            if row is None:
                raise LookupError("pairing code is invalid or expired")
            if row["claimed_at"] is not None:
                # A duplicate Discord delivery or a second claimant must not
                # invalidate the owner's already-claimed request.
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
                "AND channel_id = ? AND enabled = 1",
                (application_id, guild_id, channel_id),
            ).fetchone()
            if conflict is not None:
                raise ValueError("channel is already paired")
            claimed_at = now.isoformat()
            self._db.execute(
                "UPDATE pairings SET claimed_application_id = ?, claimed_guild_id = ?, "
                "claimed_channel_id = ?, claimed_user_id = ?, claimed_at = ? WHERE id = ?",
                (application_id, guild_id, channel_id, user_id, claimed_at, row["id"]),
            )
            updated = self._db.execute(
                "SELECT * FROM pairings WHERE id = ?", (row["id"],)
            ).fetchone()
            assert updated is not None
            return self._pairing(updated)

    def pending_for_installation(self, installation_id: str) -> list[Pairing]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM pairings WHERE installation_id = ? AND status = 'pending' "
                "AND claimed_at IS NOT NULL",
                (installation_id,),
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
            self._check_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT * FROM pairings WHERE id = ? AND installation_id = ? "
                "AND status = 'pending'",
                (pairing_id, installation_id),
            ).fetchone()
            if row is None or row["claimed_at"] is None:
                raise LookupError("pairing is not awaiting confirmation")
            conflict = self._db.execute(
                "SELECT 1 FROM connections WHERE application_id = ? AND guild_id = ? "
                "AND channel_id = ? AND enabled = 1",
                (row["claimed_application_id"], row["claimed_guild_id"], row["claimed_channel_id"]),
            ).fetchone()
            if conflict is not None:
                raise ValueError("channel is already paired")
            now = utcnow()
            connection_id = str(uuid4())
            self._db.execute(
                "INSERT INTO connections (id, installation_id, profile_id, profile_name, "
                "application_id, guild_id, channel_id, owner_user_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    connection_id,
                    row["installation_id"],
                    row["profile_id"],
                    row["profile_name"],
                    row["claimed_application_id"],
                    row["claimed_guild_id"],
                    row["claimed_channel_id"],
                    row["claimed_user_id"],
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
                "AND channel_id = ? AND enabled = 1",
                (application_id, guild_id, channel_id),
            ).fetchone()
            return self._connection(row) if row else None

    def connection(self, connection_id: str) -> Connection | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
            return self._connection(row) if row else None

    def connections_for_installation(self, installation_id: str) -> list[Connection]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM connections WHERE installation_id = ? ORDER BY created_at",
                (installation_id,),
            ).fetchall()
            return [self._connection(row) for row in rows]

    def update_connection(
        self,
        connection_id: str,
        installation_id: str,
        connector_secret: str,
        **changes: object,
    ) -> Connection:
        allowed = {"enabled", "publish_address"}
        if set(changes) - allowed:
            raise ValueError("unsupported connection change")
        with self._lock, self._db:
            self._check_installation(installation_id, connector_secret)
            row = self._db.execute(
                "SELECT * FROM connections WHERE id = ? AND installation_id = ?",
                (connection_id, installation_id),
            ).fetchone()
            if row is None:
                raise LookupError("connection not found")
            values = {
                key: int(value) if isinstance(value, bool) else value
                for key, value in changes.items()
                if value is not None
            }
            if values:
                assignments = ", ".join(f"{key} = ?" for key in values)
                self._db.execute(  # noqa: S608 - assignments are allow-listed above
                    f"UPDATE connections SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608
                    (*values.values(), utcnow().isoformat(), connection_id),
                )
            updated = self._db.execute(
                "SELECT * FROM connections WHERE id = ?", (connection_id,)
            ).fetchone()
            assert updated is not None
            return self._connection(updated)

    def revoke_connection(self, connection_id: str, installation_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE connections SET enabled = 0, updated_at = ? WHERE id = ? "
                "AND installation_id = ?",
                (utcnow().isoformat(), connection_id, installation_id),
            )
            self._snapshots.pop(connection_id, None)

    def save_snapshot(
        self, connection_id: str, installation_id: str, sequence: int, snapshot: dict[str, Any]
    ) -> bool:
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT last_sequence FROM connections WHERE id = ? AND installation_id = ? "
                "AND enabled = 1",
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
            self._snapshots[connection_id] = {"sequence": sequence, "observed_at": now, **snapshot}
            return True

    def heartbeat(self, connection_id: str, installation_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE connections SET last_heartbeat_at = ?, updated_at = ? WHERE id = ? "
                "AND installation_id = ? AND enabled = 1",
                (utcnow().isoformat(), utcnow().isoformat(), connection_id, installation_id),
            )

    def snapshot(self, connection: Connection, stale_after_seconds: int) -> dict[str, Any] | None:
        with self._lock:
            snapshot = dict(self._snapshots.get(connection.id, {}))
        if not snapshot:
            return None
        heartbeat = connection.last_heartbeat_at
        snapshot["stale"] = (
            heartbeat is None or (utcnow() - heartbeat).total_seconds() > stale_after_seconds
        )
        return snapshot

    def set_status_message(self, connection_id: str, message_id: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE connections SET status_message_id = ?, updated_at = ? WHERE id = ?",
                (message_id, utcnow().isoformat(), connection_id),
            )
