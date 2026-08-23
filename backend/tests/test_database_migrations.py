from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from blockstead.database_migrations import database_url, upgrade_database


def migration_paths() -> tuple[Path, Path]:
    backend = Path(__file__).parents[1]
    return backend / "alembic.ini", backend / "migrations"


def config_for(database: Path) -> Config:
    config_path, migrations_path = migration_paths()
    config = Config(str(config_path))
    config.set_main_option("script_location", str(migrations_path))
    config.set_main_option("sqlalchemy.url", database_url(database))
    return config


def table_names(database: Path) -> set[str]:
    engine = create_engine(database_url(database))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def schedule_unique_columns(database: Path) -> set[tuple[str, ...]]:
    engine = create_engine(database_url(database))
    try:
        return {
            tuple(constraint["column_names"])
            for constraint in inspect(engine).get_unique_constraints("schedules")
        }
    finally:
        engine.dispose()


def current_revision(database: Path) -> str:
    engine = create_engine(database_url(database))
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_empty_database_upgrades_to_head(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    config_path, migrations_path = migration_paths()

    upgrade_database(database, config_path, migrations_path)

    assert table_names(database) == {
        "administrators",
        "sessions",
        "profiles",
        "audit_events",
        "schedules",
        "backups",
        "metric_samples",
        "automation_events",
        "automation_runs",
        "app_secrets",
        "notification_preferences",
        "player_sessions",
        "performance_samples",
        "diagnostic_captures",
        "backup_destination_checks",
        "password_recovery_tokens",
        "saved_setups",
        "saved_setup_variants",
        "notification_integrations",
        "notification_deliveries",
        "discord_pairings",
        "discord_connections",
        "discord_command_audits",
        "alembic_version",
    }
    assert current_revision(database) == "0019"


def test_current_0015_database_upgrades_milestone12_tables(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    config = config_for(database)
    command.upgrade(config, "0015")

    config_path, migrations_path = migration_paths()
    upgrade_database(database, config_path, migrations_path)

    assert current_revision(database) == "0019"
    assert {
        "password_recovery_tokens",
        "saved_setups",
        "saved_setup_variants",
        "notification_integrations",
        "notification_deliveries",
        "discord_pairings",
        "discord_connections",
        "discord_command_audits",
    }.issubset(table_names(database))


def test_discord_delivery_state_migration_adds_safe_columns(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    config = config_for(database)
    command.upgrade(config, "0018")

    engine = create_engine(database_url(database))
    try:
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        now = datetime(2026, 8, 23, 12, tzinfo=UTC)
        with engine.begin() as connection:
            connection.execute(
                metadata.tables["administrators"].insert().values(
                    id="admin-1",
                    username="owner",
                    password_hash="redacted",  # noqa: S106 - inert migration fixture
                    role="owner",
                    disabled=False,
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["profiles"].insert().values(
                    id="profile-1",
                    name="Legacy published profile",
                    server_directory="legacy-published-profile",
                    distribution="vanilla",
                    is_fixture=False,
                    created_at=now,
                )
            )
            connection.execute(
                metadata.tables["discord_connections"].insert().values(
                    id="connection-1",
                    admin_id="admin-1",
                    profile_id="profile-1",
                    application_id="1535816544951476324",
                    guild_id="900000000000000002",
                    channel_id="900000000000000003",
                    owner_user_id="900000000000000004",
                    authorized_user_ids="[]",
                    authorized_role_ids="[]",
                    enabled=True,
                    publish_address=True,
                    last_sequence=0,
                    last_status_payload="{}",
                    created_at=now,
                    updated_at=now,
                )
            )
    finally:
        engine.dispose()

    config_path, migrations_path = migration_paths()
    upgrade_database(database, config_path, migrations_path)

    engine = create_engine(database_url(database))
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("discord_connections")}
        with engine.connect() as connection:
            share_address = connection.execute(
                text(
                    "SELECT share_address FROM discord_connections "
                    "WHERE id = 'connection-1'"
                )
            ).scalar_one()
    finally:
        engine.dispose()
    assert {
        "share_address",
        "last_delivery_result",
        "last_delivery_at",
        "last_delivery_detail",
    }.issubset(columns)
    assert bool(share_address) is True


def test_unversioned_initial_schema_is_stamped_then_upgraded(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    config = config_for(database)
    command.upgrade(config, "0001")
    engine = create_engine(database_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()
    config_path, migrations_path = migration_paths()

    upgrade_database(database, config_path, migrations_path)

    assert "schedules" in table_names(database)
    assert ("profile_id",) in schedule_unique_columns(database)
    assert "backups" in table_names(database)
    assert "metric_samples" in table_names(database)
    assert current_revision(database) == "0019"


def test_unversioned_current_schema_is_stamped_at_head(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    config = config_for(database)
    command.upgrade(config, "0001")
    engine = create_engine(database_url(database))
    try:
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        sa.Table(
            "schedules",
            metadata,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("profile_id", sa.String(36), sa.ForeignKey("profiles.id"), nullable=False),
            sa.Column("enabled", sa.Boolean, nullable=False),
            sa.Column("start_time", sa.String(5)),
            sa.Column("stop_time", sa.String(5)),
            sa.Column("backup_before_stop", sa.Boolean, nullable=False),
            sa.Column("power_off_after_stop", sa.Boolean, nullable=False),
            sa.Column("wake_time", sa.String(5)),
            sa.Column("last_start_date", sa.String(10)),
            sa.Column("last_stop_date", sa.String(10)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        ).create(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))
    finally:
        engine.dispose()
    config_path, migrations_path = migration_paths()

    upgrade_database(database, config_path, migrations_path)

    assert ("profile_id",) in schedule_unique_columns(database)
    assert "backups" in table_names(database)
    assert "metric_samples" in table_names(database)
    assert current_revision(database) == "0019"


def test_unknown_unversioned_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "blockstead.db"
    engine = create_engine(database_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE mystery (id INTEGER PRIMARY KEY)"))
    finally:
        engine.dispose()
    config_path, migrations_path = migration_paths()

    with pytest.raises(RuntimeError, match="unrecognized unversioned schema"):
        upgrade_database(database, config_path, migrations_path)
