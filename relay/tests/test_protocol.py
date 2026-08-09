from discord_relay.protocol import command_definition, parse_interaction


def test_commands_are_scoped_to_read_only_status_features() -> None:
    command = command_definition()
    names = {item["name"] for item in command["options"]}
    assert names == {"status", "players", "address", "refresh", "pair", "unpair", "help", "setup"}
    assert not names.intersection({"start", "stop", "console", "files", "backup"})


def test_interaction_parser_keeps_exact_discord_scope() -> None:
    interaction = parse_interaction(
        {
            "id": "interaction-1",
            "token": "interaction-token",
            "application_id": "1535816544951476324",
            "guild_id": "guild-1",
            "channel_id": "channel-1",
            "member": {"user": {"id": "user-1"}},
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
    assert interaction.guild_id == "guild-1"
    assert interaction.channel_id == "channel-1"
