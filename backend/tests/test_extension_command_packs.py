from blockstead.command_catalog import catalog_payload, render_guided_command
from blockstead.extension_command_packs import active_provider_ids
from blockstead.extensions import ExtensionEntry


def entry(
    identifier: str,
    *,
    display_name: str | None = None,
    loaders: list[str] | None = None,
    readable: bool = True,
) -> ExtensionEntry:
    return ExtensionEntry(
        file_name=f"{identifier}.jar",
        size_bytes=1,
        sha256="a",
        sha512="b",
        kind="paper-plugin" if (loaders or ["paper"])[0] == "paper" else "fabric-mod",
        loaders=loaders or ["paper"],
        identifier=identifier,
        display_name=display_name,
        version="1.0",
        minecraft_constraint="1.21",
        environment="*",
        dependencies=[],
        readable=readable,
    )


def test_active_provider_detection_ignores_disabled_unreadable_and_wrong_loader() -> None:
    active = [
        entry("WorldGuard"),
        entry("WorldEdit"),
        entry("not-worldedit", loaders=["fabric"]),
        entry("CoreProtect", readable=False),
    ]
    assert active_provider_ids("paper", active) >= {"worldedit", "worldguard", "spark"}
    assert "coreprotect" not in active_provider_ids("paper", active)


def test_worldguard_requires_worldedit() -> None:
    assert "worldguard" not in active_provider_ids("paper", [entry("WorldGuard")])
    assert "worldguard" in active_provider_ids("paper", [entry("WorldGuard"), entry("WorldEdit")])


def test_client_only_or_incompatible_entries_do_not_unlock_commands() -> None:
    client_only = entry("carpet", loaders=["fabric"])
    client_only.environment = "client"
    assert "carpet" not in active_provider_ids("fabric", [client_only], "1.21")

    incompatible = entry("carpet", loaders=["fabric"])
    incompatible.minecraft_constraint = "1.20"
    assert "carpet" not in active_provider_ids("fabric", [incompatible], "1.21")


def test_catalog_origin_can_identify_a_renamed_jar() -> None:
    installed = entry("renamed-plugin", loaders=["paper"])
    assert "coreprotect" in active_provider_ids(
        "paper",
        [installed],
        "1.21",
        {installed.file_name: "coreprotect"},
    )


def test_catalog_filters_extension_commands_and_labels_provider() -> None:
    catalog = catalog_payload({"geyser"})
    ids = {command["id"] for command in catalog["commands"]}
    assert catalog["schema_version"] == 2
    assert "geyser_version" in ids
    assert "spark_tps" not in ids
    geyser = next(command for command in catalog["commands"] if command["id"] == "geyser_version")
    assert geyser["provider_id"] == "geyser"


def test_hidden_provider_command_cannot_be_rendered() -> None:
    try:
        render_guided_command("geyser_version", {}, set())
    except ValueError as exc:
        assert "guided command" in str(exc)
    else:
        raise AssertionError("A hidden extension command was rendered")

    command, safety = render_guided_command("geyser_version", {}, {"geyser"})
    assert command == "geyser version"
    assert safety == "normal"
