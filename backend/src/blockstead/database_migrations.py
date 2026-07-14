import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

INITIAL_SCHEMA = {
    "administrators": frozenset({"id", "username", "password_hash", "created_at"}),
    "sessions": frozenset(
        {"id", "admin_id", "token_hash", "csrf_hash", "expires_at", "created_at"}
    ),
    "profiles": frozenset(
        {
            "id",
            "name",
            "server_directory",
            "distribution",
            "minecraft_version",
            "is_fixture",
            "created_at",
        }
    ),
    "audit_events": frozenset(
        {"id", "admin_id", "category", "result", "safe_detail", "created_at"}
    ),
}
SCHEDULE_COLUMNS = frozenset(
    {
        "id",
        "profile_id",
        "enabled",
        "start_time",
        "stop_time",
        "backup_before_stop",
        "power_off_after_stop",
        "wake_time",
        "last_start_date",
        "last_stop_date",
        "created_at",
    }
)
LEGACY_SCHEMAS: dict[str, dict[str, frozenset[str]]] = {
    "0001": INITIAL_SCHEMA,
    "0002": {**INITIAL_SCHEMA, "schedules": SCHEDULE_COLUMNS},
}
LEGACY_REVISIONS = {frozenset(schema): revision for revision, schema in LEGACY_SCHEMAS.items()}


def database_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.resolve()}"


def upgrade_database(
    database_path: Path,
    alembic_config_path: Path,
    migrations_path: Path,
) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(alembic_config_path))
    config.set_main_option("script_location", str(migrations_path.resolve()))
    config.set_main_option("sqlalchemy.url", database_url(database_path))

    engine = create_engine(database_url(database_path))
    try:
        inspector = inspect(engine)
        tables = frozenset(inspector.get_table_names())
        columns = {
            table: frozenset(column["name"] for column in inspector.get_columns(table))
            for table in tables
            if table != "alembic_version"
        }
    finally:
        engine.dispose()

    if tables and "alembic_version" not in tables:
        revision = LEGACY_REVISIONS.get(tables)
        if revision is None:
            names = ", ".join(sorted(tables))
            raise RuntimeError(
                "The existing Blockstead database has an unrecognized unversioned schema "
                f"({names}). Restore a known-good database or migrate it manually."
            )
        if columns != LEGACY_SCHEMAS[revision]:
            raise RuntimeError(
                "The existing Blockstead database has unexpected columns in its unversioned "
                "schema. Restore a known-good database or migrate it manually."
            )
        command.stamp(config, revision)

    command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade a Blockstead database safely.")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--migrations", required=True, type=Path)
    args = parser.parse_args()
    upgrade_database(args.database, args.config, args.migrations)


if __name__ == "__main__":
    main()
