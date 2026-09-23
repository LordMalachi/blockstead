import pytest

from discord_relay.protocol import (
    PROTOCOL_VERSION,
    RelayReply,
    command_definition,
    parse_interaction,
)

INTERACTION_ID = "920000000000000001"
APPLICATION_ID = "1535816544951476324"
GUILD_ID = "920000000000000002"
CHANNEL_ID = "920000000000000003"
USER_ID = "920000000000000004"


def test_commands_are_scoped_to_read_only_status_features() -> None:
    command = command_definition()
    names = {item["name"] for item in command["options"]}
    assert names == {"status", "players", "address", "refresh", "pair", "unpair", "help", "setup"}
    assert not names.intersection({"start", "stop", "console", "files", "backup"})


def test_interaction_parser_keeps_exact_discord_scope() -> None:
    interaction = parse_interaction(
        {
            "id": INTERACTION_ID,
            "token": "interaction-token",
            "application_id": APPLICATION_ID,
            "guild_id": GUILD_ID,
            "channel_id": CHANNEL_ID,
            "member": {
                "user": {"id": USER_ID},
                "roles": ["987654321098765432", "987654321098765432", "not-a-role"],
            },
            "data": {
                "name": "blockstead",
                "options": [
                    {
                        "type": 1,
                        "name": "pair",
                        "options": [{"type": 3, "name": "code", "value": "PAIR1234"}],
                    }
                ],
            },
        }
    )
    assert interaction.subcommand == "pair"
    assert interaction.options == {"code": "PAIR1234"}
    assert interaction.guild_id == GUILD_ID
    assert interaction.channel_id == CHANNEL_ID
    assert interaction.role_ids == ("987654321098765432",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "interaction-1"),
        ("application_id", "not-a-snowflake"),
        ("guild_id", "123"),
        ("channel_id", ""),
    ],
)
def test_interaction_parser_rejects_malformed_binding_snowflakes(
    field: str, value: str
) -> None:
    payload: dict[str, object] = {
        "id": INTERACTION_ID,
        "token": "interaction-token",
        "application_id": APPLICATION_ID,
        "guild_id": GUILD_ID,
        "channel_id": CHANNEL_ID,
        "member": {"user": {"id": USER_ID}, "roles": []},
        "data": {"name": "blockstead"},
    }
    payload[field] = value
    with pytest.raises(ValueError):
        parse_interaction(payload)


def test_protocol_version_is_explicitly_pinned() -> None:
    assert PROTOCOL_VERSION == 1


def test_reply_contract_exposes_ephemeral_policy() -> None:
    assert RelayReply("private").ephemeral is True
    assert RelayReply("public", ephemeral=False).ephemeral is False
