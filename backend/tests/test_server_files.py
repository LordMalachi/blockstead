import json
from pathlib import Path

from blockstead.server_files import MAX_FILE_BYTES, read_players, read_settings


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
    assert view.other_keys == ["custom-key"]
    assert "must-never-appear" not in view.model_dump_json()


def test_settings_missing_file(tmp_path: Path) -> None:
    view = read_settings(tmp_path)
    assert view.present is False
    assert view.settings == []


def test_settings_oversized_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("a=b\n" * (MAX_FILE_BYTES // 4 + 1))
    assert read_settings(tmp_path).present is False


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
