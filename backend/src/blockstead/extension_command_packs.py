"""Curated extension recommendations and safe command-pack availability.

The registry is deliberately static: jar metadata can identify a provider, but
it must never turn arbitrary plugin-provided text into an executable command.
Live catalog version checks are handled by the API layer; this module owns the
stable product identities, aliases, dependencies, and command definitions.
"""

import re
from dataclasses import dataclass
from typing import Literal

from .extensions import ExtensionEntry

CatalogSource = Literal["modrinth", "hangar"]
RuntimeMode = Literal["extension", "paper-capability"]


@dataclass(frozen=True)
class ExtensionRecommendation:
    id: str
    project_id: str
    source: CatalogSource
    title: str
    purpose: str
    supported_distributions: frozenset[str]
    aliases: frozenset[str]
    command_pack_id: str | None = None
    dependencies: tuple[str, ...] = ()
    conflict_group: str | None = None
    runtime_mode: RuntimeMode = "extension"


def _recommendation(
    id: str,
    project_id: str,
    title: str,
    purpose: str,
    distributions: set[str],
    aliases: set[str],
    *,
    command_pack_id: str | None = None,
    dependencies: tuple[str, ...] = (),
    conflict_group: str | None = None,
    runtime_mode: RuntimeMode = "extension",
    source: CatalogSource = "modrinth",
) -> ExtensionRecommendation:
    return ExtensionRecommendation(
        id=id,
        project_id=project_id,
        source=source,
        title=title,
        purpose=purpose,
        supported_distributions=frozenset(distributions),
        aliases=frozenset(alias.casefold() for alias in aliases),
        command_pack_id=command_pack_id,
        dependencies=dependencies,
        conflict_group=conflict_group,
        runtime_mode=runtime_mode,
    )


RECOMMENDATIONS: tuple[ExtensionRecommendation, ...] = (
    _recommendation(
        "essentialsx",
        "essentialsx",
        "EssentialsX",
        "Homes, warps, teleports, broadcasts, and everyday server utilities.",
        {"paper"},
        {"essentials", "essentialsx"},
        command_pack_id="essentialsx",
    ),
    _recommendation(
        "luckperms",
        "luckperms",
        "LuckPerms",
        "Groups, permissions, tracks, and player access management.",
        {"paper", "fabric", "forge", "neoforge"},
        {"luckperms", "luckperms-fabric", "luckperms-forge"},
        command_pack_id="luckperms",
    ),
    _recommendation(
        "worldedit",
        "worldedit",
        "WorldEdit",
        "Selections, schematics, map editing, and build administration.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"worldedit", "worldedit-mod"},
        command_pack_id="worldedit",
    ),
    _recommendation(
        "worldguard",
        "worldguard",
        "WorldGuard",
        "Protect regions and control gameplay rules in selected areas.",
        {"paper"},
        {"worldguard"},
        command_pack_id="worldguard",
        dependencies=("worldedit",),
    ),
    _recommendation(
        "coreprotect",
        "coreprotect",
        "CoreProtect",
        "Audit block changes and investigate or reverse griefing safely.",
        {"paper"},
        {"coreprotect", "core-protect"},
        command_pack_id="coreprotect",
    ),
    _recommendation(
        "spark",
        "spark",
        "spark",
        "TPS, health reports, profiling, memory, and server diagnostics.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"spark"},
        command_pack_id="spark",
        runtime_mode="paper-capability",
    ),
    _recommendation(
        "chunky",
        "chunky",
        "Chunky",
        "Pre-generate chunks before players explore them.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"chunky"},
        command_pack_id="chunky",
    ),
    _recommendation(
        "viaversion",
        "viaversion",
        "ViaVersion",
        "Allow compatible newer Java clients to join older server versions.",
        {"paper", "fabric"},
        {"viaversion", "via-version"},
        command_pack_id="viaversion",
    ),
    _recommendation(
        "geyser",
        "geyser",
        "Geyser",
        "Bridge Bedrock players onto a Java server.",
        {"paper", "fabric", "neoforge"},
        {"geyser", "geyser-spigot", "geyser-fabric", "geyser-neoforge"},
        command_pack_id="geyser",
    ),
    _recommendation(
        "floodgate",
        "floodgate",
        "Floodgate",
        "Companion identity support for Geyser online-mode servers.",
        {"paper", "fabric", "neoforge"},
        {"floodgate", "floodgate-spigot", "floodgate-fabric", "floodgate-neoforge"},
        dependencies=("geyser",),
    ),
    _recommendation(
        "simple-voice-chat",
        "simple-voice-chat",
        "Simple Voice Chat",
        "Proximity voice chat for compatible clients and servers.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"voicechat", "simple-voice-chat", "simplevoicechat"},
    ),
    _recommendation(
        "squaremap",
        "squaremap",
        "squaremap",
        "A lightweight live browser map for the server world.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"squaremap"},
        conflict_group="world-map",
    ),
    _recommendation(
        "bluemap",
        "bluemap",
        "BlueMap",
        "A 3D browser map of the server world.",
        {"paper", "fabric", "forge", "neoforge", "quilt"},
        {"bluemap", "blue-map"},
        conflict_group="world-map",
    ),
    _recommendation(
        "carpet",
        "carpet",
        "Carpet",
        "Technical server rules, tick controls, logging, and farm diagnostics.",
        {"fabric"},
        {"carpet"},
        command_pack_id="carpet",
    ),
    _recommendation(
        "lithium",
        "lithium",
        "Lithium",
        "General-purpose game-logic optimizations that preserve vanilla behavior.",
        {"fabric", "neoforge", "quilt"},
        {"lithium"},
    ),
    _recommendation(
        "ferritecore",
        "ferrite-core",
        "FerriteCore",
        "Memory-use optimizations for modded servers and clients.",
        {"fabric", "forge", "neoforge", "quilt"},
        {"ferritecore", "ferrite-core"},
    ),
)

RECOMMENDATION_BY_ID = {item.id: item for item in RECOMMENDATIONS}

# Active entries are the only evidence used to expose command packs. Disabled
# entries remain useful installer state but must never unlock console actions.
_NATIVE_LOADERS: dict[str, frozenset[str]] = {
    "paper": frozenset({"paper"}),
    "fabric": frozenset({"fabric"}),
    "forge": frozenset({"forge"}),
    "neoforge": frozenset({"neoforge"}),
    "quilt": frozenset({"quilt", "fabric"}),
}


def _entry_names(entry: ExtensionEntry) -> set[str]:
    values = {entry.identifier, entry.display_name}
    values.add(entry.file_name.rsplit("/", 1)[-1].removesuffix(".jar"))
    return {value.casefold() for value in values if value}


def _entry_matches_recommendation(
    entry: ExtensionEntry,
    recommendation: ExtensionRecommendation,
    origin_project_ids: dict[str, str] | None = None,
) -> bool:
    names = _entry_names(entry)
    origin_id = (origin_project_ids or {}).get(entry.file_name)
    if origin_id:
        names.add(origin_id.casefold())
    return any(
        name == alias or name.startswith(f"{alias}-") or name.startswith(f"{alias}_")
        for name in names
        for alias in recommendation.aliases
    )


def _version_parts(value: str) -> tuple[int, ...] | None:
    match = re.match(r"^\s*(\d+(?:\.\d+){0,2})", value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare_versions(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    padded_left = left + (0,) * (width - len(left))
    padded_right = right + (0,) * (width - len(right))
    return (padded_left > padded_right) - (padded_left < padded_right)


def _constraint_matches(constraint: str | None, minecraft_version: str | None) -> bool:
    """Reject only metadata that clearly excludes the profile version.

    Extension metadata uses several loader-specific syntaxes.  This parser
    handles the common exact, wildcard, comparison, and bracketed range forms;
    unknown syntax remains allowed so metadata does not create a false block.
    """
    if not constraint or not minecraft_version:
        return True
    current = _version_parts(minecraft_version)
    if current is None:
        return True
    value = constraint.strip().casefold()
    if value in {"*", "x", "any", "all"}:
        return True

    if "," in value and value[:1] in "([":
        lower_text, upper_text = (part.strip() for part in value[1:-1].split(",", 1))
        lower = _version_parts(lower_text)
        upper = _version_parts(upper_text)
        if lower is not None:
            comparison = _compare_versions(current, lower)
            if comparison < 0 or (comparison == 0 and value[0] == "("):
                return False
        if upper is not None:
            comparison = _compare_versions(current, upper)
            if comparison > 0 or (comparison == 0 and value[-1] == ")"):
                return False
        return True

    comparisons = re.findall(r"(>=|<=|>|<)\s*(\d+(?:\.\d+){0,2})", value)
    if comparisons:
        for operator, version_text in comparisons:
            target = _version_parts(version_text)
            if target is None:
                continue
            comparison = _compare_versions(current, target)
            if operator == ">=" and comparison < 0:
                return False
            if operator == ">" and comparison <= 0:
                return False
            if operator == "<=" and comparison > 0:
                return False
            if operator == "<" and comparison >= 0:
                return False
        return True

    versions = re.findall(r"\d+(?:\.\d+){0,2}", value)
    if not versions:
        return True
    return any(
        _compare_versions(current[: len(target)], target) == 0
        for target in (_version_parts(version) for version in versions)
        if target is not None
    )


def _entry_matches_distribution(
    entry: ExtensionEntry, distribution: str, minecraft_version: str | None = None
) -> bool:
    native = _NATIVE_LOADERS.get(distribution, frozenset())
    return bool(
        entry.readable
        and entry.environment != "client"
        and entry.loaders
        and native.intersection(entry.loaders)
        and _constraint_matches(entry.minecraft_constraint, minecraft_version)
    )


def _has_bundled_spark(distribution: str) -> bool:
    # Current Paper releases expose spark commands as part of Paper itself.
    return distribution == "paper"


def active_provider_ids(
    distribution: str,
    entries: list[ExtensionEntry],
    minecraft_version: str | None = None,
    origin_project_ids: dict[str, str] | None = None,
) -> set[str]:
    detected: set[str] = set()
    for recommendation in RECOMMENDATIONS:
        if distribution not in recommendation.supported_distributions:
            continue
        if recommendation.runtime_mode == "paper-capability":
            if _has_bundled_spark(distribution):
                detected.add(recommendation.id)
            continue
        if any(
            _entry_matches_distribution(entry, distribution, minecraft_version)
            and _entry_matches_recommendation(entry, recommendation, origin_project_ids)
            for entry in entries
        ):
            detected.add(recommendation.id)

    changed = True
    while changed:
        changed = False
        for recommendation in RECOMMENDATIONS:
            if recommendation.id in detected and all(
                dependency in detected for dependency in recommendation.dependencies
            ):
                continue
            if recommendation.id in detected and not all(
                dependency in detected for dependency in recommendation.dependencies
            ):
                detected.remove(recommendation.id)
                changed = True
    return detected


def installed_state(
    recommendation: ExtensionRecommendation,
    distribution: str,
    active_entries: list[ExtensionEntry],
    disabled_entries: list[ExtensionEntry],
    minecraft_version: str | None = None,
    origin_project_ids: dict[str, str] | None = None,
) -> tuple[bool, bool]:
    if recommendation.runtime_mode == "paper-capability":
        return (_has_bundled_spark(distribution), False)
    active = any(
        _entry_matches_distribution(entry, distribution, minecraft_version)
        and _entry_matches_recommendation(entry, recommendation, origin_project_ids)
        for entry in active_entries
    )
    disabled = any(
        entry.readable and _entry_matches_recommendation(entry, recommendation, origin_project_ids)
        for entry in disabled_entries
    )
    return active, disabled


def recommendation_payload(
    distribution: str,
    active_entries: list[ExtensionEntry],
    disabled_entries: list[ExtensionEntry],
    minecraft_version: str | None = None,
    origin_project_ids: dict[str, str] | None = None,
) -> tuple[list[ExtensionRecommendation], set[str], dict[str, tuple[bool, bool]]]:
    active = active_provider_ids(
        distribution, active_entries, minecraft_version, origin_project_ids
    )
    candidates = [item for item in RECOMMENDATIONS if distribution in item.supported_distributions]
    states = {
        item.id: installed_state(
            item,
            distribution,
            active_entries,
            disabled_entries,
            minecraft_version,
            origin_project_ids,
        )
        for item in candidates
    }
    return candidates, active, states


COMMAND_PACKS: dict[str, tuple[dict[str, object], ...]] = {
    "essentialsx": (
        {
            "id": "essentialsx_spawn",
            "label": "Send a player to spawn",
            "root": "spawn",
            "category": "EssentialsX",
            "description": "Send a named player to the EssentialsX spawn location.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "target",
                    "label": "Player",
                    "kind": "player",
                    "required": True,
                    "allow_selectors": False,
                    "source": "players",
                }
            ],
        },
        {
            "id": "essentialsx_tpa",
            "label": "Request a teleport",
            "root": "tpa",
            "category": "EssentialsX",
            "description": "Send a teleport request to a named player.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "target",
                    "label": "Player",
                    "kind": "player",
                    "required": True,
                    "allow_selectors": False,
                    "source": "players",
                }
            ],
        },
        {
            "id": "essentialsx_broadcast",
            "label": "Broadcast with EssentialsX",
            "root": "broadcast",
            "category": "EssentialsX",
            "description": "Send a formatted announcement through EssentialsX.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "message",
                    "label": "Message",
                    "kind": "text",
                    "required": True,
                    "max_length": 256,
                }
            ],
        },
    ),
    "luckperms": (
        {
            "id": "luckperms_user_info",
            "label": "Inspect LuckPerms user",
            "root": "lp user",
            "category": "LuckPerms",
            "description": "Show a player’s groups, permissions, and metadata.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "target",
                    "label": "Player",
                    "kind": "player",
                    "required": True,
                    "allow_selectors": False,
                    "source": "players",
                },
                {
                    "key": "detail",
                    "label": "Detail",
                    "kind": "choice",
                    "required": True,
                    "options": ["info", "permission info", "parent info", "meta info"],
                },
            ],
        },
        {
            "id": "luckperms_group_permission",
            "label": "Set a group permission",
            "root": "lp group",
            "category": "LuckPerms",
            "description": "Grant or remove one permission node from a LuckPerms group.",
            "safety": "danger",
            "arguments": [
                {
                    "key": "group",
                    "label": "Group",
                    "kind": "text",
                    "required": True,
                    "max_length": 64,
                },
                {
                    "key": "action",
                    "label": "Action",
                    "kind": "choice",
                    "required": True,
                    "options": ["permission set", "permission unset"],
                },
                {
                    "key": "node",
                    "label": "Permission node",
                    "kind": "text",
                    "required": True,
                    "max_length": 160,
                },
                {"key": "value", "label": "Value", "kind": "boolean", "required": False},
            ],
        },
    ),
    "worldedit": (
        {
            "id": "worldedit_version",
            "label": "Check WorldEdit version",
            "root": "we version",
            "category": "WorldEdit",
            "description": "Show the installed WorldEdit version and platform.",
            "safety": "normal",
            "arguments": [],
        },
    ),
    "worldguard": (
        {
            "id": "worldguard_regions",
            "label": "List protected regions",
            "root": "rg list",
            "category": "WorldGuard",
            "description": "List protected regions known to WorldGuard.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "worldguard_region_info",
            "label": "Inspect a protected region",
            "root": "rg info",
            "category": "WorldGuard",
            "description": "Show members, owners, flags, and bounds for a region.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "region",
                    "label": "Region",
                    "kind": "text",
                    "required": True,
                    "max_length": 64,
                }
            ],
        },
        {
            "id": "worldguard_flag",
            "label": "Set a region flag",
            "root": "rg flag",
            "category": "WorldGuard",
            "description": "Change one gameplay flag on a protected region.",
            "safety": "caution",
            "arguments": [
                {
                    "key": "region",
                    "label": "Region",
                    "kind": "text",
                    "required": True,
                    "max_length": 64,
                },
                {
                    "key": "flag",
                    "label": "Flag",
                    "kind": "text",
                    "required": True,
                    "max_length": 64,
                },
                {
                    "key": "value",
                    "label": "Value",
                    "kind": "text",
                    "required": True,
                    "max_length": 160,
                },
            ],
        },
    ),
    "coreprotect": (
        {
            "id": "coreprotect_status",
            "label": "Check CoreProtect status",
            "root": "co status",
            "category": "CoreProtect",
            "description": "Show the CoreProtect version and logging status.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "coreprotect_lookup",
            "label": "Look up block history",
            "root": "co lookup",
            "category": "CoreProtect",
            "description": "Search recorded activity using CoreProtect filters.",
            "safety": "normal",
            "arguments": [
                {
                    "key": "filters",
                    "label": "Filters",
                    "kind": "text",
                    "required": True,
                    "placeholder": "u:Player t:1h r:#global",
                    "max_length": 240,
                }
            ],
        },
        {
            "id": "coreprotect_rollback_preview",
            "label": "Preview a CoreProtect rollback",
            "root": "co rollback",
            "category": "CoreProtect",
            "description": "Preview the blocks that a rollback would change without applying it.",
            "safety": "caution",
            "arguments": [
                {
                    "key": "filters",
                    "label": "Filters",
                    "kind": "text",
                    "required": True,
                    "placeholder": "u:Player t:1h r:#global",
                    "max_length": 240,
                },
                {
                    "key": "preview",
                    "label": "Preview",
                    "kind": "choice",
                    "required": True,
                    "options": ["#preview"],
                },
            ],
        },
        {
            "id": "coreprotect_rollback",
            "label": "Apply a CoreProtect rollback",
            "root": "co rollback",
            "category": "CoreProtect",
            "description": "Reverse recorded changes after reviewing the exact scope.",
            "safety": "danger",
            "arguments": [
                {
                    "key": "filters",
                    "label": "Filters",
                    "kind": "text",
                    "required": True,
                    "placeholder": "u:Player t:1h r:#global",
                    "max_length": 240,
                }
            ],
        },
    ),
    "spark": (
        {
            "id": "spark_tps",
            "label": "Read spark TPS",
            "root": "spark tps",
            "category": "spark",
            "description": "Show current server TPS and CPU information.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "spark_health",
            "label": "Generate a spark health report",
            "root": "spark health",
            "category": "spark",
            "description": "Generate a report covering TPS, CPU, memory, and disk usage.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "spark_profiler_start",
            "label": "Start a timed spark profile",
            "root": "spark profiler start --timeout",
            "category": "spark",
            "description": "Capture a bounded CPU profile for performance diagnosis.",
            "safety": "caution",
            "arguments": [
                {
                    "key": "seconds",
                    "label": "Duration in seconds",
                    "kind": "integer",
                    "required": True,
                    "minimum": 5,
                    "maximum": 300,
                    "suggestions": [30, 60, 120],
                }
            ],
        },
        {
            "id": "spark_profiler_stop",
            "label": "Stop the spark profile",
            "root": "spark profiler stop",
            "category": "spark",
            "description": "Stop the current profile and request its result.",
            "safety": "caution",
            "arguments": [],
        },
    ),
    "chunky": (
        {
            "id": "chunky_progress",
            "label": "Read Chunky progress",
            "root": "chunky progress",
            "category": "Chunky",
            "description": "Show all active and saved pre-generation tasks.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "chunky_start",
            "label": "Start Chunky generation",
            "root": "chunky start",
            "category": "Chunky",
            "description": "Start pre-generation using the current Chunky selection.",
            "safety": "caution",
            "arguments": [],
        },
        {
            "id": "chunky_pause",
            "label": "Pause Chunky generation",
            "root": "chunky pause",
            "category": "Chunky",
            "description": "Pause current pre-generation tasks and save their progress.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "chunky_cancel",
            "label": "Cancel Chunky generation",
            "root": "chunky cancel",
            "category": "Chunky",
            "description": "Cancel current pre-generation tasks.",
            "safety": "danger",
            "arguments": [],
        },
    ),
    "viaversion": (
        {
            "id": "viaversion_list",
            "label": "List ViaVersion clients",
            "root": "viaversion list",
            "category": "ViaVersion",
            "description": "Show players currently connected through ViaVersion.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "viaversion_status",
            "label": "Check ViaVersion status",
            "root": "viaversion",
            "category": "ViaVersion",
            "description": "Show the installed ViaVersion release and protocol state.",
            "safety": "normal",
            "arguments": [],
        },
    ),
    "geyser": (
        {
            "id": "geyser_list",
            "label": "List Bedrock players",
            "root": "geyser list",
            "category": "Geyser",
            "description": "List players currently connected through Geyser.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "geyser_version",
            "label": "Check Geyser version",
            "root": "geyser version",
            "category": "Geyser",
            "description": "Show the Geyser version and check its update state.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "geyser_dump",
            "label": "Create a Geyser diagnostic dump",
            "root": "geyser dump",
            "category": "Geyser",
            "description": "Create diagnostic information for a Geyser support report.",
            "safety": "caution",
            "arguments": [],
        },
    ),
    "carpet": (
        {
            "id": "carpet_rules",
            "label": "List Carpet rules",
            "root": "carpet list",
            "category": "Carpet",
            "description": "Show the technical rules exposed by Carpet.",
            "safety": "normal",
            "arguments": [],
        },
        {
            "id": "carpet_log_tps",
            "label": "Log Carpet TPS",
            "root": "log tps",
            "category": "Carpet",
            "description": "Toggle Carpet’s server TPS logging.",
            "safety": "caution",
            "arguments": [],
        },
        {
            "id": "carpet_tick_query",
            "label": "Read Carpet tick state",
            "root": "tick query",
            "category": "Carpet",
            "description": "Show the current Carpet tick state.",
            "safety": "normal",
            "arguments": [],
        },
    ),
}


def command_entries(provider_ids: set[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for provider_id in sorted(provider_ids):
        for command in COMMAND_PACKS.get(provider_id, ()):
            entries.append({**command, "provider_id": provider_id})
    return entries
