from pathlib import Path

from blockstead.discord_relay import ensure_relay_identity


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
