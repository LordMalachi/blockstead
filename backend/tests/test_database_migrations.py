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
        "alembic_version",
    }
    assert current_revision(database) == "0007"


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
    assert current_revision(database) == "0007"


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
    assert current_revision(database) == "0007"


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
