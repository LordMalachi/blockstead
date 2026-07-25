"""Deterministic maintenance preflight and reviewed change plans.

Nothing in this module contacts the network, executes a change, or writes to a
server folder.  It maps evidence Blockstead has already collected onto bounded
findings and one ordered, readable plan that the owner reviews before any
existing, independently protected operation runs.

Two rules shape every branch here:

* An unknown answer is reported as unknown.  A compatibility source Blockstead
  could not read never becomes "safe to upgrade".
* A destructive or version-changing plan always carries a required protection
  step and an explicit stop/restart expectation, so the owner sees both before
  a confirmation is offered anywhere in the product.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field

CATALOG_VERSION = "2026.07.1"

ChangeId = Literal[
    "extension_update",
    "extension_install",
    "settings_change",
    "world_files",
    "server_upgrade",
]
FindingStatus = Literal["ready", "attention", "blocked", "unknown", "info"]
Readiness = Literal["ready", "ready_with_warnings", "blocked"]
StepRequirement = Literal["required", "recommended", "not_needed"]
RestartExpectation = Literal["required", "recommended", "not_needed", "unknown"]

# A backup needs working room for the archive plus ordinary server headroom.
BACKUP_OVERHEAD_BYTES = 512 * 1024 * 1024
ARCHIVE_SIZE_FACTOR = 1.2
# A protection point older than this is still real, but is called out as stale.
FRESH_PROTECTION_HOURS = 24
# An automation event this close to the change would collide with it.
COLLISION_MINUTES = 60


class MaintenanceRequest(BaseModel):
    change_id: ChangeId


class ChangeDefinition(BaseModel):
    id: ChangeId
    title: str
    summary: str
    workspace: str
    requires_stopped_server: bool
    version_changing: bool
    destructive: bool
    restart_expectation: RestartExpectation
    checks: list[str]


class MaintenanceFinding(BaseModel):
    id: str
    label: str
    status: FindingStatus
    detail: str
    recommendation: str | None = None


class PlanStep(BaseModel):
    id: str
    label: str
    detail: str
    requirement: StepRequirement
    # Every step in this plan is performed by the owner through an existing,
    # separately protected workspace; Blockstead does not run a plan for them.
    performed_by: Literal["owner"] = "owner"
    route: str | None = None


class ProtectionPoint(BaseModel):
    verified: bool
    detail: str
    backup_id: str | None = None
    created_at: str | None = None
    age_hours: float | None = None


class MaintenancePlan(BaseModel):
    catalog_version: str = CATALOG_VERSION
    plan_id: str
    profile_id: str
    change: ChangeDefinition
    readiness: Readiness
    headline: str
    detail: str
    findings: list[MaintenanceFinding]
    steps: list[PlanStep]
    protection: ProtectionPoint
    restart: RestartExpectation
    restart_detail: str
    blockers: list[str] = Field(default_factory=list)
    reviewed_at: str


class MaintenanceCatalog(BaseModel):
    version: str = CATALOG_VERSION
    changes: list[ChangeDefinition]


@dataclass(frozen=True)
class BackupPoint:
    id: str
    created_at: datetime
    verified: bool
    # Why verification failed, when it did; empty when the archive verified.
    problem: str = ""
    size_bytes: int | None = None


@dataclass(frozen=True)
class MaintenanceContext:
    profile_id: str
    profile_name: str
    distribution: str
    distribution_label: str
    minecraft_version: str | None
    is_fixture: bool
    state: str
    selected_server_active: bool
    state_reason: str
    # None means the local status protocol did not answer, never "nobody here".
    online_players: int | None
    max_players: int
    last_backup: BackupPoint | None
    disk_free_bytes: int
    disk_total_bytes: int
    world_size_bytes: int | None
    # "file.jar@version" per installed extension, sorted; the review fingerprint.
    extension_signature: tuple[str, ...]
    extension_warnings: tuple[str, ...]
    required_java_major: int | None
    compatible_java_found: bool | None
    launch_problem: str | None
    pending_restart: bool
    pending_restart_detail: str
    next_operation_label: str | None
    next_operation_at: datetime | None
    occupied_by: str | None
    now: datetime
    upgrade_source_available: bool = False
    recovery_paths: tuple[str, ...] = field(default_factory=tuple)


CHANGES: tuple[ChangeDefinition, ...] = (
    ChangeDefinition(
        id="extension_update",
        title="Update installed mods or plugins",
        summary=(
            "Replace installed extension files with newer compatible versions. "
            "Blockstead keeps the previous file so the change can be undone."
        ),
        workspace="mods",
        requires_stopped_server=True,
        version_changing=True,
        destructive=False,
        restart_expectation="required",
        checks=[
            "Who is connected right now",
            "Whether the server is stopped for a safe extension change",
            "Whether a verified protection point exists",
            "Whether the data disk has room for a fresh backup",
            "Known compatibility limits for this server",
        ],
    ),
    ChangeDefinition(
        id="extension_install",
        title="Add a mod, plugin, or modpack",
        summary=(
            "Install new extension files into this server. New content can change "
            "world generation and save data, so it is treated as a risky change."
        ),
        workspace="mods",
        requires_stopped_server=True,
        version_changing=False,
        destructive=True,
        restart_expectation="required",
        checks=[
            "Who is connected right now",
            "Whether the server is stopped for a safe extension change",
            "Whether a verified protection point exists",
            "Whether the data disk has room for a fresh backup",
            "Known compatibility limits for this server",
        ],
    ),
    ChangeDefinition(
        id="settings_change",
        title="Change server settings",
        summary=(
            "Edit server.properties through the guided editor. Blockstead snapshots "
            "the file before every save; most values need a restart to take effect."
        ),
        workspace="settings",
        requires_stopped_server=False,
        version_changing=False,
        destructive=False,
        restart_expectation="recommended",
        checks=[
            "Who is connected right now",
            "Whether a restart is already pending",
            "Whether a verified protection point exists",
            "Known compatibility limits for this server",
        ],
    ),
    ChangeDefinition(
        id="world_files",
        title="Edit or replace world files",
        summary=(
            "Change files inside the world folder through the file workspace. "
            "This is the one change that can lose player progress."
        ),
        workspace="files",
        requires_stopped_server=True,
        version_changing=False,
        destructive=True,
        restart_expectation="required",
        checks=[
            "Who is connected right now",
            "Whether the server is stopped so the world is not being written",
            "Whether a verified protection point exists",
            "Whether the data disk has room for a fresh backup",
            "Whether an automated operation is due soon",
        ],
    ),
    ChangeDefinition(
        id="server_upgrade",
        title="Upgrade the server or loader version",
        summary=(
            "Move this server to a different Minecraft or loader version. "
            "Blockstead only offers this once it can verify the upgrade itself."
        ),
        workspace="overview",
        requires_stopped_server=True,
        version_changing=True,
        destructive=True,
        restart_expectation="required",
        checks=[
            "Whether a verified upgrade source is available",
            "Who is connected right now",
            "Whether the server is stopped",
            "Whether a verified protection point exists",
            "Whether the installed Java runtime matches the target version",
        ],
    ),
)

_CHANGE_BY_ID = {change.id: change for change in CHANGES}
_RUNNING_STATES = {"RUNNING", "DEGRADED"}
_TRANSITIONAL_STATES = {"STARTING", "STOPPING"}


def catalog() -> MaintenanceCatalog:
    return MaintenanceCatalog(changes=list(CHANGES))


def change_definition(change_id: ChangeId) -> ChangeDefinition:
    return _CHANGE_BY_ID[change_id]


def _finding(
    id: str,
    label: str,
    status: FindingStatus,
    detail: str,
    recommendation: str | None = None,
) -> MaintenanceFinding:
    return MaintenanceFinding(
        id=id, label=label, status=status, detail=detail, recommendation=recommendation
    )


def _running(context: MaintenanceContext) -> bool:
    return context.selected_server_active and context.state in _RUNNING_STATES


def _server_state_finding(
    context: MaintenanceContext, change: ChangeDefinition
) -> MaintenanceFinding:
    label = "Server state"
    if context.selected_server_active and context.state in _TRANSITIONAL_STATES:
        return _finding(
            "server-state",
            label,
            "blocked",
            f"{context.profile_name} is {context.state.lower()}. "
            "Blockstead cannot plan a change while the process is changing state.",
            "Wait for the server to settle, then review this change again.",
        )
    if context.occupied_by is not None:
        return _finding(
            "server-state",
            label,
            "blocked",
            f"{context.occupied_by} is using the managed server process. "
            "Blockstead runs one server at a time.",
            f"Stop {context.occupied_by} before changing {context.profile_name}.",
        )
    if not change.requires_stopped_server:
        if _running(context):
            return _finding(
                "server-state",
                label,
                "ready",
                f"{context.profile_name} is running. This change does not require a stop.",
            )
        return _finding("server-state", label, "ready", f"{context.profile_name} is stopped.")
    if _running(context):
        return _finding(
            "server-state",
            label,
            "attention",
            f"{context.profile_name} is running, and this change is only applied "
            "to a stopped server.",
            "The plan below stops the server before the change is applied.",
        )
    return _finding(
        "server-state",
        label,
        "ready",
        f"{context.profile_name} is stopped, which is what this change requires.",
    )


def _player_finding(context: MaintenanceContext) -> MaintenanceFinding:
    label = "Connected players"
    if not _running(context):
        return _finding(
            "connected-players",
            label,
            "ready",
            "The server is not running, so nobody is connected to interrupt.",
        )
    if context.online_players is None:
        return _finding(
            "connected-players",
            label,
            "unknown",
            "Minecraft did not answer Blockstead's local status check, so the number "
            "of connected players is unknown.",
            "Announce the change in the console before you begin.",
        )
    if context.online_players == 0:
        return _finding(
            "connected-players",
            label,
            "ready",
            f"Minecraft reported 0 of {context.max_players} players connected.",
        )
    plural = "player is" if context.online_players == 1 else "players are"
    return _finding(
        "connected-players",
        label,
        "attention",
        f"{context.online_players} {plural} connected right now.",
        "The plan below announces the change and counts down before the stop.",
    )


def _protection_finding(
    context: MaintenanceContext, change: ChangeDefinition
) -> tuple[MaintenanceFinding, ProtectionPoint]:
    label = "Protection point"
    matters = change.destructive or change.version_changing
    backup = context.last_backup
    if backup is None:
        point = ProtectionPoint(
            verified=False,
            detail="This server has no completed backup to fall back on.",
        )
        return (
            _finding(
                "protection-point",
                label,
                "attention" if matters else "info",
                "This server has no completed backup, so there is nothing to restore "
                "if the change goes wrong.",
                "The plan below creates and verifies a backup before the change.",
            ),
            point,
        )

    age_hours = max(0.0, (context.now - backup.created_at).total_seconds() / 3600)
    created_at = backup.created_at.isoformat()
    if not backup.verified:
        point = ProtectionPoint(
            verified=False,
            detail=backup.problem or "The latest backup did not pass verification.",
            backup_id=backup.id,
            created_at=created_at,
            age_hours=age_hours,
        )
        return (
            _finding(
                "protection-point",
                label,
                "attention" if matters else "info",
                f"The latest backup did not verify: {point.detail}",
                "Treat this server as unprotected and create a fresh verified backup.",
            ),
            point,
        )

    point = ProtectionPoint(
        verified=True,
        detail="The latest backup matches its manifest and Blockstead's recorded checksum.",
        backup_id=backup.id,
        created_at=created_at,
        age_hours=age_hours,
    )
    if age_hours > FRESH_PROTECTION_HOURS:
        return (
            _finding(
                "protection-point",
                label,
                "attention" if matters else "info",
                f"The newest verified backup is {age_hours / 24:.1f} days old, so play "
                "since then is not protected.",
                "The plan below creates a fresh backup before the change.",
            ),
            point,
        )
    return (
        _finding(
            "protection-point",
            label,
            "ready",
            f"A verified backup from {age_hours:.1f} hours ago can be restored.",
        ),
        point,
    )


def _disk_finding(context: MaintenanceContext) -> MaintenanceFinding:
    label = "Disk space for a backup"
    if context.world_size_bytes is None:
        return _finding(
            "disk-space",
            label,
            "unknown",
            "Blockstead could not measure this world, so it cannot say whether a "
            f"backup fits in the {_gib(context.disk_free_bytes)} free on the data disk.",
            "Check free space yourself before creating the pre-change backup.",
        )
    needed = int(context.world_size_bytes * ARCHIVE_SIZE_FACTOR) + BACKUP_OVERHEAD_BYTES
    if context.disk_free_bytes < needed:
        return _finding(
            "disk-space",
            label,
            "blocked",
            f"A backup of this world needs about {_gib(needed)}, and only "
            f"{_gib(context.disk_free_bytes)} is free on the data disk.",
            "Free disk space or remove old backups before making this change.",
        )
    if context.disk_free_bytes < needed * 2:
        return _finding(
            "disk-space",
            label,
            "attention",
            f"{_gib(context.disk_free_bytes)} is free and a backup needs about "
            f"{_gib(needed)}. There is room for this change but little to spare.",
            "Review backup retention after the change.",
        )
    return _finding(
        "disk-space",
        label,
        "ready",
        f"{_gib(context.disk_free_bytes)} is free; a backup of this world needs "
        f"about {_gib(needed)}.",
    )


def _pending_restart_finding(context: MaintenanceContext) -> MaintenanceFinding:
    label = "Pending restart"
    if not _running(context):
        return _finding(
            "pending-restart",
            label,
            "ready",
            "The server is stopped, so its next start already picks up every saved change.",
        )
    if context.pending_restart:
        return _finding(
            "pending-restart",
            label,
            "attention",
            context.pending_restart_detail,
            "Expect this restart to apply the earlier change as well as this one.",
        )
    return _finding(
        "pending-restart",
        label,
        "ready",
        "No saved change is waiting for a restart on this running server.",
    )


def _compatibility_finding(
    context: MaintenanceContext, change: ChangeDefinition
) -> MaintenanceFinding:
    label = "Compatibility limits"
    if change.id == "server_upgrade" and not context.upgrade_source_available:
        return _finding(
            "compatibility",
            label,
            "blocked",
            f"Blockstead has no verified upgrade source for {context.distribution_label}, "
            "so it cannot tell you whether a newer version is safe to install here.",
            "Upgrade this server with its own installer, then re-import the folder.",
        )
    if context.is_fixture:
        return _finding(
            "compatibility",
            label,
            "info",
            "This is the built-in practice server. Its compatibility is fixed and no "
            "real Minecraft files are involved.",
        )
    problems: list[str] = []
    if context.distribution == "unknown":
        problems.append("Blockstead did not recognize this server's distribution.")
    if context.launch_problem:
        problems.append(context.launch_problem)
    if context.compatible_java_found is False:
        required = context.required_java_major or "a supported version"
        problems.append(f"No Java {required} runtime was found on this computer.")
    if problems:
        status: FindingStatus = "blocked" if change.version_changing else "attention"
        return _finding(
            "compatibility",
            label,
            status,
            " ".join(problems),
            "Resolve the readiness item on the server overview before this change.",
        )
    if context.compatible_java_found is None or context.required_java_major is None:
        return _finding(
            "compatibility",
            label,
            "unknown",
            "Blockstead does not know which Java version this Minecraft version needs, "
            "so it cannot confirm the runtime matches.",
            "Confirm the runtime requirement in the distribution's own release notes.",
        )
    if context.extension_warnings:
        return _finding(
            "compatibility",
            label,
            "attention",
            " ".join(context.extension_warnings),
            "Review the flagged extensions before applying the change.",
        )
    return _finding(
        "compatibility",
        label,
        "ready",
        f"Java {context.required_java_major} is available and the launch files for "
        f"{context.distribution_label} are complete.",
    )


def _schedule_finding(context: MaintenanceContext) -> MaintenanceFinding:
    label = "Automated operations"
    if context.next_operation_at is None or context.next_operation_label is None:
        return _finding(
            "scheduled-operation",
            label,
            "ready",
            "No automated start, stop, or backup is scheduled for this server.",
        )
    minutes = (context.next_operation_at - context.now).total_seconds() / 60
    when = context.next_operation_at.strftime("%H:%M")
    if 0 <= minutes <= COLLISION_MINUTES:
        return _finding(
            "scheduled-operation",
            label,
            "attention",
            f"“{context.next_operation_label}” is due at {when}, about "
            f"{minutes:.0f} minutes from now, and would run during this change.",
            "Move the scheduled operation or wait until it has finished.",
        )
    return _finding(
        "scheduled-operation",
        label,
        "ready",
        f"The next automated operation, “{context.next_operation_label}”, is not due until {when}.",
    )


def _gib(value: int) -> str:
    return f"{value / (1024**3):.1f} GB"


def _steps(
    context: MaintenanceContext,
    change: ChangeDefinition,
    findings: list[MaintenanceFinding],
    protection: ProtectionPoint,
) -> list[PlanStep]:
    by_id = {finding.id: finding for finding in findings}
    running = _running(context)
    base = f"/servers/{context.profile_id}"
    steps: list[PlanStep] = []

    players = by_id["connected-players"]
    if running:
        announce_required = players.status in {"attention", "unknown"}
        steps.append(
            PlanStep(
                id="announce",
                label="Tell connected players and count down",
                detail=(
                    "Send a console message so nobody loses progress to a surprise stop."
                    if announce_required
                    else "Nobody was reported online, but an announcement costs nothing."
                ),
                requirement="required" if announce_required else "recommended",
                route=f"{base}/console",
            )
        )
        steps.append(
            PlanStep(
                id="save",
                label="Save the world to disk",
                detail=("Run save-all flush so the backup captures everything played so far."),
                requirement="required",
                route=f"{base}/console",
            )
        )

    protection_matters = change.destructive or change.version_changing
    fresh_protection = (
        protection.verified
        and protection.age_hours is not None
        and protection.age_hours <= FRESH_PROTECTION_HOURS
    )
    steps.append(
        PlanStep(
            id="backup",
            label="Create a backup and verify it",
            detail=(
                "This is the only way back from this change, so it is required before "
                "anything is applied."
                if protection_matters
                else "A fresh verified backup keeps recovery current even for a reversible change."
            ),
            # A destructive or version-changing plan always carries a required
            # protection step; a fresh verified point only softens the wording.
            requirement="required"
            if protection_matters
            else ("recommended" if not fresh_protection else "not_needed"),
            route=f"{base}/backups",
        )
    )

    if change.requires_stopped_server:
        steps.append(
            PlanStep(
                id="stop",
                label="Stop the server safely",
                detail=(
                    "Blockstead applies this change only to a stopped server, so the "
                    "files are not being written while they change."
                ),
                requirement="required" if running else "not_needed",
                route=f"{base}/console",
            )
        )

    steps.append(
        PlanStep(
            id="apply",
            label=f"Apply the change: {change.title.lower()}",
            detail=(
                "Every write still runs through the workspace that owns it, with its "
                "own confirmation and recovery snapshot."
            ),
            requirement="required",
            route=f"{base}/{change.workspace}",
        )
    )

    if change.version_changing or change.requires_stopped_server:
        steps.append(
            PlanStep(
                id="validate",
                label="Check the launch plan before starting",
                detail=(
                    "Confirm the server overview still shows a complete launcher and a "
                    "matching Java runtime."
                ),
                requirement="required",
                route=f"{base}/overview#readiness",
            )
        )

    steps.append(
        PlanStep(
            id="restart",
            label=_restart_label(change, running),
            detail=_restart_detail(change, running),
            requirement="required"
            if change.restart_expectation == "required" and running
            else "recommended",
            route=f"{base}/console",
        )
    )
    return steps


def _restart_label(change: ChangeDefinition, running: bool) -> str:
    if change.requires_stopped_server:
        return "Start the server again when you are ready"
    if running:
        return "Restart to apply the change"
    return "Start the server when you are ready"


def _restart_detail(change: ChangeDefinition, running: bool) -> str:
    if change.restart_expectation == "required":
        return (
            "This change does not take effect until the server starts again. "
            "Starting is a separate, deliberate step: nothing restarts on its own."
        )
    return (
        "Most settings only take effect on the next start. Blockstead leaves the "
        "choice of when to restart to you."
    )


def _fingerprint(context: MaintenanceContext, change: ChangeDefinition) -> str:
    """Identify the evidence this review was based on.

    A schedule built from a reviewed plan carries this value so a plan whose
    evidence has since changed can be recognized instead of silently reused.
    """

    parts = [
        CATALOG_VERSION,
        change.id,
        context.profile_id,
        context.distribution,
        context.minecraft_version or "",
        "running" if _running(context) else "stopped",
        context.last_backup.id if context.last_backup else "",
        "verified" if context.last_backup and context.last_backup.verified else "unverified",
        context.launch_problem or "",
        str(context.required_java_major or ""),
        *context.extension_signature,
    ]
    return sha256("".join(parts).encode("utf-8")).hexdigest()[:16]


def assess(context: MaintenanceContext, request: MaintenanceRequest) -> MaintenancePlan:
    """Build the preflight findings and the reviewed plan for one change."""

    change = change_definition(request.change_id)
    findings: list[MaintenanceFinding] = [
        _server_state_finding(context, change),
        _player_finding(context),
    ]
    protection_finding, protection = _protection_finding(context, change)
    findings.append(protection_finding)
    findings.append(_disk_finding(context))
    findings.append(_pending_restart_finding(context))
    findings.append(_compatibility_finding(context, change))
    findings.append(_schedule_finding(context))

    blockers = [
        finding.recommendation or finding.detail
        for finding in findings
        if finding.status == "blocked"
    ]
    if blockers:
        readiness: Readiness = "blocked"
    elif any(finding.status in {"attention", "unknown"} for finding in findings):
        readiness = "ready_with_warnings"
    else:
        readiness = "ready"

    steps = _steps(context, change, findings, protection)
    headline, detail = _summary(context, change, readiness, findings)
    return MaintenancePlan(
        plan_id=_fingerprint(context, change),
        profile_id=context.profile_id,
        change=change,
        readiness=readiness,
        headline=headline,
        detail=detail,
        findings=findings,
        steps=steps,
        protection=protection,
        restart=change.restart_expectation,
        restart_detail=_restart_detail(change, _running(context)),
        blockers=blockers,
        reviewed_at=context.now.isoformat(),
    )


def _summary(
    context: MaintenanceContext,
    change: ChangeDefinition,
    readiness: Readiness,
    findings: list[MaintenanceFinding],
) -> tuple[str, str]:
    if readiness == "blocked":
        return (
            f"Blockstead cannot call this change safe on {context.profile_name} yet",
            "One or more checks came back as a stop. Nothing has changed, and the "
            "steps below stay unavailable until the blocker is resolved.",
        )
    attention = [finding.label for finding in findings if finding.status == "attention"]
    unknown = [finding.label for finding in findings if finding.status == "unknown"]
    if readiness == "ready":
        return (
            f"{change.title} looks safe to do now on {context.profile_name}",
            "Every check Blockstead can make came back clear. Follow the plan below; "
            "each step still asks for its own confirmation.",
        )
    parts: list[str] = []
    if attention:
        parts.append("needs attention: " + ", ".join(attention).lower())
    if unknown:
        parts.append("could not be checked: " + ", ".join(unknown).lower())
    return (
        f"{change.title} is possible on {context.profile_name}, with things to know",
        "Nothing blocks this change, but " + "; ".join(parts) + ".",
    )


def audit_detail(plan: MaintenancePlan, profile_name: str) -> str:
    """One safe, readable Activity line recording what the preflight found."""

    counts: dict[str, int] = {}
    for finding in plan.findings:
        counts[finding.status] = counts.get(finding.status, 0) + 1
    summary = ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))
    return (
        f"Reviewed “{plan.change.title}” on {profile_name}: {plan.readiness} "
        f"({summary}); plan {plan.plan_id}"
    )


def stale_after(reviewed_at: datetime) -> datetime:
    """When a reviewed plan should be checked again before it is acted on."""

    return reviewed_at + timedelta(hours=FRESH_PROTECTION_HOURS)
