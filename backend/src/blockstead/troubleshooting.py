"""Deterministic, evidence-first troubleshooting playbooks.

The catalog deliberately contains no free-form diagnosis or executable script
content.  Each playbook maps observed Blockstead state to bounded findings and
registered repair identifiers that the frontend can route to existing,
independently protected API operations.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .server_files import PlayersView

CATALOG_VERSION = "2026.07.1"

ProblemId = Literal[
    "player_cannot_join",
    "local_connection",
    "public_connection",
    "server_wont_start",
    "timeouts_or_lag",
]
CheckStatus = Literal["passed", "flagged", "unknown", "info"]
Certainty = Literal["confirmed", "possible", "none"]
Outcome = Literal["problem_found", "possible_cause", "no_problem_found", "incomplete"]


class TroubleshootingRequest(BaseModel):
    problem_id: ProblemId
    player_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{3,16}$", max_length=16)

    @model_validator(mode="after")
    def require_player_name(self) -> "TroubleshootingRequest":
        if self.problem_id == "player_cannot_join" and self.player_name is None:
            raise ValueError("Choose the player who cannot join.")
        return self


class TroubleshootingRepairRequest(BaseModel):
    action_id: Literal["allowlist_add", "pardon_player", "enable_lan"]
    player_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_]{3,16}$", max_length=16)

    @model_validator(mode="after")
    def require_player_for_player_action(self) -> "TroubleshootingRepairRequest":
        if self.action_id in {"allowlist_add", "pardon_player"} and self.player_name is None:
            raise ValueError("Choose the player affected by this repair.")
        return self


class KnowledgeSource(BaseModel):
    id: str
    title: str
    url: str
    publisher: str
    checked_at: str


class ProblemDefinition(BaseModel):
    id: ProblemId
    title: str
    summary: str
    requires_player_name: bool = False
    checks: list[str]
    possible_solutions: list[str]
    source_ids: list[str]


class TroubleshootingCheck(BaseModel):
    id: str
    label: str
    status: CheckStatus
    certainty: Certainty = "none"
    detail: str
    source_ids: list[str] = Field(default_factory=list)


class TroubleshootingAction(BaseModel):
    id: Literal["allowlist_add", "pardon_player", "enable_lan"]
    label: str
    description: str
    impact: str
    confirmation: str
    available: bool
    blockers: list[str] = Field(default_factory=list)
    destructive: Literal[False] = False


class TroubleshootingAssessment(BaseModel):
    catalog_version: str = CATALOG_VERSION
    problem: ProblemDefinition
    outcome: Outcome
    headline: str
    detail: str
    checks: list[TroubleshootingCheck]
    actions: list[TroubleshootingAction]
    next_steps: list[str]
    sources: list[KnowledgeSource]


class TroubleshootingCatalog(BaseModel):
    version: str = CATALOG_VERSION
    problems: list[ProblemDefinition]
    sources: list[KnowledgeSource]


@dataclass(frozen=True)
class TroubleshootingContext:
    profile_id: str
    profile_name: str
    distribution: str
    minecraft_version: str | None
    state: str
    selected_server_active: bool
    state_reason: str
    properties: dict[str, str]
    players: PlayersView
    local_status_responded: bool | None
    local_status_outcome: str | None
    join: dict[str, object]
    eula_accepted: bool | None
    required_java_major: int | None
    compatible_java_found: bool | None
    launch_problem: str | None
    disk_percent: float
    memory_percent: float
    cpu_percent: float
    recent_errors: list[str]


SOURCES: tuple[KnowledgeSource, ...] = (
    KnowledgeSource(
        id="minecraft-server-setup",
        title="How to Setup a Minecraft: Java Edition Server",
        url="https://help.minecraft.net/hc/en-us/articles/360058525452-How-to-Setup-a-Minecraft-Java-Edition-Server",
        publisher="Minecraft Help",
        checked_at="2026-07-23",
    ),
    KnowledgeSource(
        id="minecraft-multiplayer",
        title="Play Minecraft: Java Edition Online in a Multiplayer Server",
        url="https://help.minecraft.net/hc/en-us/articles/32899741198989-Play-Minecraft-Java-Edition-Online-in-a-Multiplayer-Server",
        publisher="Minecraft Help",
        checked_at="2026-07-23",
    ),
    KnowledgeSource(
        id="paper-properties",
        title="server.properties reference",
        url="https://docs.papermc.io/paper/reference/server-properties/",
        publisher="PaperMC",
        checked_at="2026-07-23",
    ),
    KnowledgeSource(
        id="paper-troubleshooting",
        title="Basic troubleshooting",
        url="https://docs.papermc.io/paper/basic-troubleshooting/",
        publisher="PaperMC",
        checked_at="2026-07-23",
    ),
    KnowledgeSource(
        id="neoforge-server",
        title="Installing a NeoForge Server",
        url="https://docs.neoforged.net/user/docs/server/",
        publisher="NeoForged",
        checked_at="2026-07-23",
    ),
)

PROBLEMS: tuple[ProblemDefinition, ...] = (
    ProblemDefinition(
        id="player_cannot_join",
        title="A specific player cannot join",
        summary=(
            "Check that the server is available and that this player is not blocked "
            "by access rules."
        ),
        requires_player_name=True,
        checks=[
            "Selected server is running",
            "Player is on the allowlist when it is enabled",
            "Player is not banned",
            "Minecraft responds to a local status request",
        ],
        possible_solutions=[
            "Add the player to the allowlist",
            "Pardon the player if they are banned",
            "Continue with connection checks when access rules pass",
        ],
        source_ids=["paper-properties", "minecraft-multiplayer"],
    ),
    ProblemDefinition(
        id="local_connection",
        title="Players on my local network cannot join",
        summary=(
            "Check the process, local Minecraft listener, configured port, bind address, "
            "and detected LAN address."
        ),
        checks=[
            "Selected server is running",
            "Minecraft responds on its configured local port",
            "The server is not restricted to this computer",
            "A usable local-network address is available",
        ],
        possible_solutions=[
            "Enable local-network listening when the server is loopback-only",
            "Use the exact local address and port Blockstead detects",
            "Review the host firewall when Blockstead's checks pass",
        ],
        source_ids=["paper-properties", "minecraft-server-setup"],
    ),
    ProblemDefinition(
        id="public_connection",
        title="Friends outside my network cannot join",
        summary=(
            "Check everything Blockstead can prove locally, then clearly identify the "
            "router and provider checks it cannot perform from inside the network."
        ),
        checks=[
            "Selected server and local Minecraft listener are available",
            "The server is not restricted to this computer",
            "A public IP can be detected",
            "External port reachability is independently confirmed",
        ],
        possible_solutions=[
            "Enable local-network listening when the server is loopback-only",
            "Forward the configured Minecraft port to this computer",
            "Check host firewall, double NAT, VPN, or carrier-grade NAT",
        ],
        source_ids=["minecraft-server-setup", "paper-properties"],
    ),
    ProblemDefinition(
        id="server_wont_start",
        title="The server will not start or keeps crashing",
        summary=(
            "Check launch prerequisites and recent recorded failures without guessing "
            "which file caused a crash."
        ),
        checks=[
            "Minecraft EULA is accepted",
            "A compatible Java runtime is installed",
            "Required launch files are present",
            "The data disk has safe working space",
            "Recent errors are available for review",
        ],
        possible_solutions=[
            "Complete the readiness item Blockstead identifies",
            "Review latest.log or the focused diagnostic report",
            "Back up and stop the server before changing plugins, mods, or world files",
        ],
        source_ids=["minecraft-server-setup", "paper-troubleshooting", "neoforge-server"],
    ),
    ProblemDefinition(
        id="timeouts_or_lag",
        title="Players time out or the server is lagging",
        summary=(
            "Check whether the server responds locally and whether host CPU, memory, "
            "or storage is under pressure."
        ),
        checks=[
            "Minecraft responds to a local status request",
            "Host CPU and memory have headroom",
            "The data disk has safe working space",
            "Recent errors are available for review",
        ],
        possible_solutions=[
            "Resolve confirmed storage or readiness problems first",
            "Compare the problem time with recent Activity",
            "Use a focused report when no measurable host cause is found",
        ],
        source_ids=["paper-troubleshooting"],
    ),
)

_PROBLEM_BY_ID = {problem.id: problem for problem in PROBLEMS}
_SOURCE_BY_ID = {source.id: source for source in SOURCES}
_RUNNING_STATES = {"RUNNING", "DEGRADED"}


def catalog() -> TroubleshootingCatalog:
    return TroubleshootingCatalog(problems=list(PROBLEMS), sources=list(SOURCES))


def _check(
    id: str,
    label: str,
    status: CheckStatus,
    detail: str,
    *,
    certainty: Certainty = "none",
    sources: list[str] | None = None,
) -> TroubleshootingCheck:
    return TroubleshootingCheck(
        id=id,
        label=label,
        status=status,
        certainty=certainty,
        detail=detail,
        source_ids=sources or [],
    )


def _server_check(context: TroubleshootingContext) -> TroubleshootingCheck:
    if context.selected_server_active and context.state in _RUNNING_STATES:
        return _check(
            "server-running",
            "Selected server is running",
            "passed",
            f"{context.profile_name} is {context.state.lower()}.",
        )
    return _check(
        "server-running",
        "Selected server is running",
        "flagged",
        f"{context.profile_name} is not currently running, so players cannot connect.",
        certainty="confirmed",
    )


def _local_status_check(context: TroubleshootingContext) -> TroubleshootingCheck:
    if context.properties.get("enable-status", "true").strip().casefold() == "false":
        return _check(
            "local-status",
            "Minecraft server-list status",
            "info",
            (
                "server.properties has enable-status=false. Minecraft intentionally withholds "
                "server-list and player-count data, but players may still connect directly."
            ),
            sources=["paper-properties"],
        )
    if not (context.selected_server_active and context.state in _RUNNING_STATES):
        return _check(
            "local-status",
            "Minecraft responds locally",
            "unknown",
            "Blockstead can run this check after the selected server is running.",
        )
    if context.local_status_outcome == "closed_early":
        return _check(
            "local-status",
            "Minecraft accepts local connections",
            "info",
            (
                "Minecraft accepted Blockstead's local TCP connection but closed the optional "
                "server-list request early. Direct player connections may still work."
            ),
        )
    if context.local_status_responded:
        return _check(
            "local-status",
            "Minecraft responds locally",
            "passed",
            "The Minecraft status protocol responded on the configured local address and port.",
        )
    return _check(
        "local-status",
        "Minecraft responds locally",
        "flagged",
        (
            "The process is running, but Minecraft did not answer Blockstead's "
            "bounded local status check."
        ),
        certainty="possible",
        sources=["paper-troubleshooting"],
    )


def _player_checks(
    context: TroubleshootingContext, player_name: str
) -> tuple[list[TroubleshootingCheck], list[TroubleshootingAction], list[str]]:
    checks = [_server_check(context)]
    actions: list[TroubleshootingAction] = []
    next_steps: list[str] = []
    normalized = player_name.casefold()
    running = context.selected_server_active and context.state == "RUNNING"
    player_names = {entry.name.casefold() for entry in context.players.allowlist.players}
    banned_names = {entry.name.casefold() for entry in context.players.bans.players}
    whitelist_enabled = context.properties.get("white-list", "false").strip().casefold() == "true"

    if whitelist_enabled:
        if not context.players.allowlist.readable:
            checks.append(
                _check(
                    "allowlist",
                    f"{player_name} is on the allowlist",
                    "unknown",
                    "The allowlist is enabled, but whitelist.json could not be read safely.",
                    sources=["paper-properties"],
                )
            )
        elif normalized in player_names:
            checks.append(
                _check(
                    "allowlist",
                    f"{player_name} is on the allowlist",
                    "passed",
                    "The allowlist is enabled and contains this player.",
                    sources=["paper-properties"],
                )
            )
        else:
            blockers = [] if running else ["Start this server before sending a player command."]
            checks.append(
                _check(
                    "allowlist",
                    f"{player_name} is on the allowlist",
                    "flagged",
                    "The allowlist is enabled, but this player is not listed.",
                    certainty="confirmed",
                    sources=["paper-properties"],
                )
            )
            actions.append(
                TroubleshootingAction(
                    id="allowlist_add",
                    label=f"Add {player_name} to the allowlist",
                    description="Send Minecraft's supported allowlist command for this player.",
                    impact=f"{player_name} will be allowed to join {context.profile_name}.",
                    confirmation=(
                        f"Add {player_name} to the allowlist for {context.profile_name}?"
                    ),
                    available=running,
                    blockers=blockers,
                )
            )
    else:
        checks.append(
            _check(
                "allowlist",
                "Allowlist access",
                "info",
                "The allowlist is disabled, so it is not blocking this player.",
                sources=["paper-properties"],
            )
        )

    if not context.players.bans.readable:
        checks.append(
            _check(
                "player-ban",
                f"{player_name} is not banned",
                "unknown",
                "banned-players.json could not be read safely.",
            )
        )
    elif normalized in banned_names:
        blockers = [] if running else ["Start this server before sending a player command."]
        checks.append(
            _check(
                "player-ban",
                f"{player_name} is not banned",
                "flagged",
                "This player appears in the server's banned-player list.",
                certainty="confirmed",
            )
        )
        actions.append(
            TroubleshootingAction(
                id="pardon_player",
                label=f"Pardon {player_name}",
                description="Send Minecraft's supported pardon command for this player.",
                impact=f"{player_name} will no longer be banned from {context.profile_name}.",
                confirmation=f"Remove the ban for {player_name} on {context.profile_name}?",
                available=running,
                blockers=blockers,
            )
        )
    else:
        checks.append(
            _check(
                "player-ban",
                f"{player_name} is not banned",
                "passed",
                "This player does not appear in the server's banned-player list.",
            )
        )

    checks.append(_local_status_check(context))
    next_steps.append(
        "If these access checks pass, continue with the local or public connection wizard."
    )
    return checks, actions, next_steps


def _connection_checks(
    context: TroubleshootingContext, *, public: bool
) -> tuple[list[TroubleshootingCheck], list[TroubleshootingAction], list[str]]:
    checks = [_server_check(context), _local_status_check(context)]
    actions: list[TroubleshootingAction] = []
    join = context.join
    local_only = join.get("local_only") is True
    bind = join.get("bind_address")
    active = context.selected_server_active and context.state in _RUNNING_STATES

    if local_only:
        blockers = ["Stop this server before changing its network bind address."] if active else []
        checks.append(
            _check(
                "network-bind",
                "Server accepts network connections",
                "flagged",
                (
                    f"server.properties binds Minecraft to {bind}, which only accepts "
                    "connections from this computer."
                ),
                certainty="confirmed",
                sources=["paper-properties"],
            )
        )
        actions.append(
            TroubleshootingAction(
                id="enable_lan",
                label="Enable local-network access",
                description=(
                    "Clear only the loopback server-ip value and create a recovery snapshot."
                ),
                impact=(
                    "Minecraft will listen on available network interfaces after its next start."
                ),
                confirmation=(
                    f"Clear the loopback-only bind for {context.profile_name}? "
                    "Blockstead will save a recovery snapshot first."
                ),
                available=not active,
                blockers=blockers,
            )
        )
    else:
        checks.append(
            _check(
                "network-bind",
                "Server accepts network connections",
                "passed",
                (
                    "The bind address is not restricted to this computer."
                    if bind
                    else "server-ip is blank, so Minecraft can listen on available interfaces."
                ),
                sources=["paper-properties"],
            )
        )

    port_value = context.properties.get("server-port", "25565").strip()
    try:
        port = int(port_value)
        valid_port = 1 <= port <= 65535
    except ValueError:
        valid_port = False
    checks.append(
        _check(
            "server-port",
            "Configured Minecraft port is valid",
            "passed" if valid_port else "flagged",
            (
                f"Minecraft is configured to listen on TCP port {port_value}."
                if valid_port
                else f"server-port={port_value!r} is not a valid TCP port."
            ),
            certainty="none" if valid_port else "confirmed",
            sources=["paper-properties"],
        )
    )

    address = join.get("address")
    if address:
        checks.append(
            _check(
                "join-address",
                "A local join address is available",
                "passed",
                f"Blockstead detected the local address {address}.",
            )
        )
    else:
        checks.append(
            _check(
                "join-address",
                "A local join address is available",
                "unknown",
                "No usable local-network address was detected on this computer.",
            )
        )

    next_steps = [
        "Test the displayed local address from another device on the same network.",
        "If Blockstead's checks pass, review the host firewall for the configured Minecraft port.",
    ]
    if public:
        public_details = join.get("public")
        public_state = (
            public_details.get("state") if isinstance(public_details, dict) else "unavailable"
        )
        detected_ip = (
            public_details.get("detected_ip") if isinstance(public_details, dict) else None
        )
        if detected_ip:
            checks.append(
                _check(
                    "public-ip",
                    "A public IP is detected",
                    "passed",
                    (
                        f"Blockstead detected public IP {detected_ip}. This does not "
                        "prove that Minecraft's port is reachable."
                    ),
                    sources=["minecraft-server-setup"],
                )
            )
        else:
            checks.append(
                _check(
                    "public-ip",
                    "A public IP is detected",
                    "unknown",
                    "Blockstead could not obtain a validated public IP.",
                    sources=["minecraft-server-setup"],
                )
            )
        checks.append(
            _check(
                "external-port",
                "Router-facing Minecraft port is reachable",
                "unknown",
                (
                    "A check from inside this network cannot prove the router and "
                    "firewall mapping. "
                    f"Current connection state: {public_state}."
                ),
                sources=["minecraft-server-setup"],
            )
        )
        next_steps = [
            (
                "Forward the router's outside Minecraft port to this computer's local "
                "address and configured port."
            ),
            (
                "Permit the configured port through the host firewall, then ask someone "
                "on another network to test."
            ),
            (
                "If forwarding still fails, check for VPN use, double NAT, or "
                "carrier-grade NAT with the internet provider."
            ),
        ]
    return checks, actions, next_steps


def _readiness_checks(
    context: TroubleshootingContext,
) -> tuple[list[TroubleshootingCheck], list[TroubleshootingAction], list[str]]:
    checks: list[TroubleshootingCheck] = []
    if context.eula_accepted is None:
        checks.append(
            _check(
                "eula",
                "Minecraft EULA is accepted",
                "info",
                "The fixture server does not require a Minecraft EULA check.",
            )
        )
    elif context.eula_accepted:
        checks.append(
            _check(
                "eula",
                "Minecraft EULA is accepted",
                "passed",
                "eula.txt records acceptance.",
                sources=["minecraft-server-setup", "neoforge-server"],
            )
        )
    else:
        checks.append(
            _check(
                "eula",
                "Minecraft EULA is accepted",
                "flagged",
                (
                    "Minecraft will not complete its first start until the EULA is "
                    "reviewed and accepted."
                ),
                certainty="confirmed",
                sources=["minecraft-server-setup", "neoforge-server"],
            )
        )

    if context.compatible_java_found is None:
        checks.append(
            _check(
                "java",
                "Compatible Java is available",
                "unknown",
                "The required Java version is unknown for this profile.",
            )
        )
    elif context.compatible_java_found:
        checks.append(
            _check(
                "java",
                "Compatible Java is available",
                "passed",
                (
                    f"A Java runtime compatible with required major "
                    f"{context.required_java_major} was found."
                    if context.required_java_major
                    else "A usable Java runtime was found."
                ),
                sources=["minecraft-server-setup"],
            )
        )
    else:
        checks.append(
            _check(
                "java",
                "Compatible Java is available",
                "flagged",
                (
                    f"No installed Java runtime satisfies required major "
                    f"{context.required_java_major}."
                ),
                certainty="confirmed",
                sources=["minecraft-server-setup", "paper-troubleshooting"],
            )
        )

    if context.launch_problem:
        checks.append(
            _check(
                "launch-files",
                "Required launch files are present",
                "flagged",
                context.launch_problem,
                certainty="confirmed",
                sources=["paper-troubleshooting", "neoforge-server"],
            )
        )
    else:
        checks.append(
            _check(
                "launch-files",
                "Required launch files are present",
                "passed",
                f"Blockstead found a supported {context.distribution} launch layout.",
            )
        )

    checks.append(_resource_check("disk", "Data disk", context.disk_percent, 90, 95))
    if context.state == "CRASHED":
        checks.append(
            _check(
                "process-state",
                "Most recent process state",
                "flagged",
                context.state_reason,
                certainty="possible",
                sources=["paper-troubleshooting"],
            )
        )
    if context.recent_errors:
        checks.append(
            _check(
                "recent-errors",
                "Recent errors are available",
                "flagged",
                f"Most recent recorded problem: {context.recent_errors[0]}",
                certainty="possible",
                sources=["paper-troubleshooting"],
            )
        )
    else:
        checks.append(
            _check(
                "recent-errors",
                "Recent errors are available",
                "info",
                "Blockstead has not recorded a recent warning or error.",
            )
        )
    return (
        checks,
        [],
        [
            "Open Server readiness for EULA, Java, or launch-file problems.",
            "Review latest.log and the focused diagnostic report before changing plugins or mods.",
            (
                "Stop the server and create a verified backup before modifying world "
                "or extension files."
            ),
        ],
    )


def _resource_check(
    id: str, label: str, value: float, warning: float, danger: float
) -> TroubleshootingCheck:
    if value >= danger:
        return _check(
            id,
            f"{label} has headroom",
            "flagged",
            f"{label} use is {value:.0f}%, which is critically high.",
            certainty="confirmed",
        )
    if value >= warning:
        return _check(
            id,
            f"{label} has headroom",
            "flagged",
            f"{label} use is {value:.0f}%, which may contribute to this problem.",
            certainty="possible",
        )
    return _check(
        id,
        f"{label} has headroom",
        "passed",
        f"{label} use is {value:.0f}%.",
    )


def _performance_checks(
    context: TroubleshootingContext,
) -> tuple[list[TroubleshootingCheck], list[TroubleshootingAction], list[str]]:
    checks = [
        _server_check(context),
        _local_status_check(context),
        _resource_check("cpu", "Host CPU", context.cpu_percent, 90, 98),
        _resource_check("memory", "Host memory", context.memory_percent, 90, 97),
        _resource_check("disk", "Data disk", context.disk_percent, 90, 95),
    ]
    if context.recent_errors:
        checks.append(
            _check(
                "recent-errors",
                "Recent errors",
                "flagged",
                f"Most recent recorded problem: {context.recent_errors[0]}",
                certainty="possible",
                sources=["paper-troubleshooting"],
            )
        )
    else:
        checks.append(
            _check(
                "recent-errors",
                "Recent errors",
                "info",
                "No recent warning or error is available to correlate with the timeout.",
            )
        )
    return (
        checks,
        [],
        [
            "Compare the time of the problem with Activity and the recent health history.",
            (
                "Download a focused support report if the local checks pass but players "
                "still time out."
            ),
            (
                "Blockstead does not claim TPS or plugin causality without a reliable "
                "capability source."
            ),
        ],
    )


def _outcome(checks: list[TroubleshootingCheck]) -> tuple[Outcome, str, str]:
    if any(check.status == "flagged" and check.certainty == "confirmed" for check in checks):
        return (
            "problem_found",
            "Blockstead found a confirmed problem",
            "Review the evidence and any available repair before making a change.",
        )
    if any(check.status == "flagged" and check.certainty == "possible" for check in checks):
        return (
            "possible_cause",
            "Blockstead found a possible cause",
            "The evidence is related, but it does not prove this is the only cause.",
        )
    if any(check.status == "unknown" for check in checks):
        return (
            "incomplete",
            "No confirmed cause was found",
            "Some checks could not be completed. Follow the remaining manual checks below.",
        )
    return (
        "no_problem_found",
        "No problem was found in these checks",
        "The available server-side checks passed. Continue with the targeted next steps.",
    )


def assess(
    request: TroubleshootingRequest, context: TroubleshootingContext
) -> TroubleshootingAssessment:
    problem = _PROBLEM_BY_ID[request.problem_id]
    if request.problem_id == "player_cannot_join":
        assert request.player_name is not None
        checks, actions, next_steps = _player_checks(context, request.player_name)
    elif request.problem_id == "local_connection":
        checks, actions, next_steps = _connection_checks(context, public=False)
    elif request.problem_id == "public_connection":
        checks, actions, next_steps = _connection_checks(context, public=True)
    elif request.problem_id == "server_wont_start":
        checks, actions, next_steps = _readiness_checks(context)
    else:
        checks, actions, next_steps = _performance_checks(context)
    outcome, headline, detail = _outcome(checks)
    source_ids = {
        *problem.source_ids,
        *(source_id for check in checks for source_id in check.source_ids),
    }
    sources = [_SOURCE_BY_ID[source.id] for source in SOURCES if source.id in source_ids]
    return TroubleshootingAssessment(
        problem=problem,
        outcome=outcome,
        headline=headline,
        detail=detail,
        checks=checks,
        actions=actions,
        next_steps=next_steps,
        sources=sources,
    )
