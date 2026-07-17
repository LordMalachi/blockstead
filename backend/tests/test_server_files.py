import json
from pathlib import Path

import pytest

from blockstead.server_files import MAX_FILE_BYTES, read_players, read_settings
from blockstead.server_settings import (
    SettingsConflictError,
    SettingsValidationError,
    apply_settings_update,
    preview_settings_update,
)


def test_settings_parse_types_and_redaction(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text(
        "#comment\n"
        "motd=Hello world\n"
        "server-port=25565\n"
        "white-list=true\n"
        "view-distance=not-a-number\n"
        "rcon.password=must-never-appear\n"
        "custom-key=kept\n",
        encoding="utf-8",
    )
    view = read_settings(tmp_path)
    assert view.present is True
    by_key = {entry.key: entry for entry in view.settings}
    assert by_key["motd"].value == "Hello world"
    assert by_key["server-port"].value == 25565
    assert by_key["white-list"].value is True
    assert by_key["view-distance"].value is None
    assert by_key["motd"].category == "Players"
    assert by_key["server-port"].minimum == 1
    assert view.revision is not None and len(view.revision) == 64
    assert view.other_keys == ["custom-key"]
    assert "must-never-appear" not in view.model_dump_json()


def test_settings_missing_file(tmp_path: Path) -> None:
    view = read_settings(tmp_path)
    assert view.present is False
    assert view.settings == []


def test_settings_oversized_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("a=b\n" * (MAX_FILE_BYTES // 4 + 1))
    assert read_settings(tmp_path).present is False


def test_guided_settings_preview_and_apply_preserve_source(tmp_path: Path) -> None:
    original = (
        "# owner comment\n"
        "motd=Old message\n"
        "max-players=20\n"
        "white-list=true\n"
        "enforce-whitelist=true\n"
        "custom-key=keep-me\n"
        "rcon.password=keep-secret\n"
    )
    properties = tmp_path / "server.properties"
    properties.write_text(original, encoding="utf-8")
    view = read_settings(tmp_path)
    assert view.revision is not None

    preview = preview_settings_update(
        tmp_path,
        view.revision,
        {"motd": "New message", "max-players": 25},
    )

    assert [change.key for change in preview.changes] == ["motd", "max-players"]
    assert preview.changes[0].before == "Old message"
    assert preview.changes[0].after == "New message"
    assert preview.restart_required is True

    result = apply_settings_update(
        tmp_path,
        tmp_path / "private-data",
        "profile-1",
        view.revision,
        {"motd": "New message", "max-players": 25},
    )

    updated = properties.read_text(encoding="utf-8")
    assert "# owner comment\n" in updated
    assert "motd=New message\n" in updated
    assert "max-players=25\n" in updated
    assert "custom-key=keep-me\n" in updated
    assert "rcon.password=keep-secret\n" in updated
    snapshot = tmp_path / "private-data" / "settings-snapshots" / "profile-1" / result.snapshot_name
    assert snapshot.read_text(encoding="utf-8") == original
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert result.revision != result.previous_revision


def test_guided_settings_reject_stale_invalid_and_incompatible_edits(tmp_path: Path) -> None:
    properties = tmp_path / "server.properties"
    properties.write_text(
        "max-players=20\nwhite-list=true\nenforce-whitelist=true\n",
        encoding="utf-8",
    )
    revision = read_settings(tmp_path).revision
    assert revision is not None

    with pytest.raises(SettingsValidationError, match="at least 1"):
        preview_settings_update(tmp_path, revision, {"max-players": 0})
    with pytest.raises(SettingsValidationError, match="requires the allowlist"):
        preview_settings_update(tmp_path, revision, {"white-list": False})

    properties.write_text(properties.read_text() + "# external edit\n", encoding="utf-8")
    with pytest.raises(SettingsConflictError, match="changed after it was opened"):
        apply_settings_update(
            tmp_path,
            tmp_path / "private-data",
            "profile-1",
            revision,
            {"max-players": 30},
        )
    assert not (tmp_path / "private-data").exists()


def test_players_parse_and_hostile_records(tmp_path: Path) -> None:
    (tmp_path / "whitelist.json").write_text(
        json.dumps(
            [
                {"uuid": "00000000-0000-0000-0000-000000000001", "name": "Alex_Fixture"},
                {"name": 12345},
                "not-a-record",
                {"uuid": ["evil"], "name": "x" * 500},
            ]
        )
    )
    (tmp_path / "ops.json").write_text(
        json.dumps([{"name": "Alex_Fixture", "level": 4, "uuid": None}])
    )
    view = read_players(tmp_path)
    assert view.allowlist.present and view.allowlist.readable
    assert [player.name for player in view.allowlist.players] == ["Alex_Fixture", "x" * 64]
    assert view.operators.players[0].level == 4
    assert view.bans.present is False


def test_players_malformed_json(tmp_path: Path) -> None:
    (tmp_path / "whitelist.json").write_text("{not json")
    (tmp_path / "ops.json").write_text('{"a": 1}')
    view = read_players(tmp_path)
    assert view.allowlist.present is True
    assert view.allowlist.readable is False
    assert view.operators.readable is False
    assert view.allowlist.players == []
