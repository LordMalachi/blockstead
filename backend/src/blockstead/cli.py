import argparse
import getpass
import sys
from pathlib import Path

from sqlalchemy import delete, select

from .config import Settings
from .db import create_session_factory
from .models import Administrator, AuditEvent, LoginSession
from .security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, hash_password


class PasswordResetError(RuntimeError):
    """A safe, actionable administrator recovery failure."""


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordResetError(
            f"The new password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordResetError(
            f"The new password must be no more than {MAX_PASSWORD_LENGTH} characters."
        )


def prompt_for_new_password() -> str:
    password = getpass.getpass("New Blockstead administrator password: ")
    validate_new_password(password)
    confirmation = getpass.getpass("Enter the new password again: ")
    if password != confirmation:
        raise PasswordResetError("The passwords did not match. Nothing was changed.")
    return password


def reset_administrator_password(database_path: Path, password: str) -> str:
    """Replace the sole administrator password and revoke all login sessions."""
    validate_new_password(password)
    if not database_path.is_file():
        raise PasswordResetError(
            f"No Blockstead database was found at {database_path}. Nothing was changed."
        )

    password_hash = hash_password(password)
    factory = create_session_factory(database_path)
    with factory.begin() as db:
        administrators = list(db.scalars(select(Administrator)).all())
        if not administrators:
            raise PasswordResetError(
                "No administrator account exists yet. Create it in the Blockstead dashboard."
            )
        if len(administrators) != 1:
            raise PasswordResetError(
                "More than one administrator account exists, so recovery cannot safely choose one."
            )

        administrator = administrators[0]
        administrator.password_hash = password_hash
        db.execute(delete(LoginSession))
        db.add(
            AuditEvent(
                admin_id=administrator.id,
                category="security",
                result="success",
                safe_detail="Administrator password reset from the local system.",
            )
        )
        username = administrator.username
    return username


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blockstead")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-config")
    reset_parser = commands.add_parser(
        "reset-password", description="Reset the local Blockstead administrator password."
    )
    reset_parser.add_argument(
        "--database",
        type=Path,
        help="Database path (defaults to BLOCKSTEAD_DATA_DIR/blockstead.db).",
    )
    args = parser.parse_args(argv)

    if args.command == "validate-config":
        settings = Settings()
        settings.prepare()
        print(f"Configuration valid. Binding to {settings.bind_host}:{settings.port}.")
        return 0

    settings = Settings()
    database_path = args.database or settings.data_dir / "blockstead.db"
    try:
        password = prompt_for_new_password()
        username = reset_administrator_password(database_path, password)
    except (EOFError, KeyboardInterrupt):
        print("\nPassword reset cancelled. Nothing was changed.", file=sys.stderr)
        return 1
    except PasswordResetError as exc:
        print(f"Password reset failed: {exc}", file=sys.stderr)
        return 1

    print(f'Password reset for administrator "{username}".')
    print("All existing Blockstead browser sessions have been signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
