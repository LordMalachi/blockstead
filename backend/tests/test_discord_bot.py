from pathlib import Path

from blockstead.config import Settings
from blockstead.discord_bot import (
    blockstead_command_definition,
    discord_configuration,
    discord_install_url,
    parse_interaction,
)


def test_discord_configuration_never_returns_the_bot_token() -> None:
    token = "secret-token-that-must-not-be-returned"  # noqa: S105
    payload = discord_configuration(
        Settings(
            _env_file=None,
            discord_application_id="1535816544951476324",
            discord_public_key="7f6109a4ad05a65d46f7721e245df151edca263bbf62eaecc82d6b06f295e51b",
            discord_bot_token=token,
        )
    )
    assert payload["bot_ready"] is True
    assert token not in repr(payload)
    assert discord_install_url("1535816544951476324").endswith("permissions=19456")


def test_gateway_interaction_parser_keeps_only_command_identity() -> None:
    interaction = parse_interaction(
        {
            "id": "900000000000000001",
            "application_id": "1535816544951476324",
            "token": "interaction-token",
            "guild_id": "900000000000000002",
            "channel_id": "900000000000000003",
            "member": {"user": {"id": "900000000000000004"}, "roles": ["900000000000000005"]},
            "data": {
                "name": "blockstead",
                "options": [
                    {
                        "type": 1,
                        "name": "pair",
                        "options": [{"type": 3, "name": "code", "value": "ABCD2345"}],
                    }
                ],
                "irrelevant_payload": "not retained",
            },
            "untrusted_extra": "not retained",
        }
    )
    assert interaction.subcommand == "pair"
    assert interaction.options == {"code": "ABCD2345"}
    assert interaction.role_ids == ("900000000000000005",)
    assert not hasattr(interaction, "untrusted_extra")


def test_command_definition_is_read_only_and_does_not_request_privileged_intents() -> None:
    command = blockstead_command_definition()
    names = {item["name"] for item in command["options"] if isinstance(item, dict)}
    assert names == {
        "status", "players", "address", "refresh", "pair", "unpair", "help", "setup"
    }
    pair = next(item for item in command["options"] if item["name"] == "pair")
    assert pair["options"][0]["required"] is True


def test_discord_status_panel_config_can_be_created_without_server_files(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None, data_dir=tmp_path / "data", server_root=tmp_path / "servers"
    )
    assert discord_configuration(settings)["mode"] == "not_configured"
