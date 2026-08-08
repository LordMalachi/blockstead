import asyncio
import hashlib
import json
import logging
import re
import secrets
import shutil
import stat
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, cast

import httpx
import psutil
from fastapi import (
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from . import __version__, updates
from .activity import (
    list_activity,
    preferences_for,
    preferences_payload,
    recovery_path,
)
from .backups import (
    BackupArchive,
    BackupError,
    RestoreError,
    backup_directory,
    create_backup_archive,
    mirror_backup_archive,
    perform_recovery_drill,
    perform_restore,
    plan_restore,
    verify_backup_archive,
)
from .backups import (
    world_roots as backup_world_roots,
)
from .catalog import CatalogError, PlannedFile
from .command_catalog import GuidedCommandRequest, catalog_payload, render_guided_command
from .config import Settings
from .curseforge import (
    PROJECT_ID_PATTERN as CURSEFORGE_PROJECT_PATTERN,
)
from .curseforge import (
    list_categories as curseforge_categories,
)
from .curseforge import (
    list_project_versions as curseforge_versions,
)
from .curseforge import (
    plan_install as curseforge_plan_install,
)
from .curseforge import (
    search as curseforge_search,
)
from .db import Base, create_session_factory
from .diagnostic_captures import (
    DiagnosticCaptureError,
    resolve_capture_path,
    write_transcript,
)
from .diagnostics import attach_logging, build_report
from .distributions import (
    DISTRIBUTIONS,
    LaunchPlanError,
    launch_arguments,
    required_java_major,
)
from .extension_command_packs import (
    ExtensionRecommendation,
    active_provider_ids,
    recommendation_payload,
)
from .extension_ops import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_CHECKSUMS,
    ExtensionOpsError,
    checksum_matches,
    create_manual_staging_directory,
    create_staging_directory,
    disabled_directory,
    ensure_managed_directory,
    place_upload,
    promote_staged_files,
    set_all_enabled,
    set_enabled,
    stage_uploaded_jar,
)
from .extension_ops import (
    remove as remove_extension,
)
from .extension_origins import (
    OriginRegistryError,
    forget_origin,
    load_origin_map,
    record_catalog_files,
    record_existing_origin,
    record_local_files,
)
from .extension_updates import (
    ExtensionRecoveryError,
    ExtensionUpdateReview,
)
from .extension_updates import (
    build_review as build_extension_update_review,
)
from .extension_updates import (
    discard_recovery as discard_extension_recovery,
)
from .extension_updates import (
    finalize_recovery as finalize_extension_recovery,
)
from .extension_updates import (
    prepare_recovery as prepare_extension_recovery,
)
from .extension_updates import (
    rollback_update as rollback_extension_update,
)
from .extensions import ExtensionEntry, ExtensionsView, inspect_extension_jar, read_extensions
from .file_paths import CATEGORIES as FILE_CATEGORIES
from .file_paths import FileCategory, FilePathError
from .hangar import (
    PROJECT_PATH_PATTERN as HANGAR_PROJECT_PATTERN,
)
from .hangar import (
    list_categories as hangar_categories,
)
from .hangar import (
    list_project_versions as hangar_versions,
)
from .hangar import (
    plan_install as hangar_plan_install,
)
from .hangar import (
    search as hangar_search,
)
from .import_scan import (
    UPLOAD_PREFIX,
    canonical_child,
    directory_overlap,
    promote_staging,
    purge_stale_uploads,
    safe_relative_path,
    scan_server,
)
from .java_runtime import discover_java_runtimes, find_java
from .loader_migration import (
    MigrationApplyRequest,
    MigrationReviewRequest,
    classify_extensions,
    copy_worlds,
    discover_world_roots,
    review_fingerprint,
    safe_level_name,
)
from .loader_migration import (
    world_roots as migration_world_roots,
)
from .loadout_lockfiles import (
    MAX_LOCKFILE_BYTES,
    OriginMap,
    build_loadout_lockfile,
    review_loadout_lockfile,
    serialize_loadout_lockfile,
)
from .maintenance import (
    BACKUP_OVERHEAD_BYTES,
    FRESH_PROTECTION_HOURS,
    BackupPoint,
    MaintenanceContext,
    MaintenancePlan,
    MaintenanceRequest,
    MaintenanceScheduleRequest,
)
from .maintenance import (
    assess as assess_maintenance,
)
from .maintenance import (
    audit_detail as maintenance_audit_detail,
)
from .maintenance import (
    catalog as maintenance_catalog,
)
from .manual_imports import (
    MAX_IMPORT_FILES,
    ManualImportApplyRequest,
    cleanup_expired,
    load_manifest,
    save_manifest,
)
from .mod_configs import (
    ModConfigError,
    list_mod_configs,
    read_mod_config,
    write_mod_config,
)
from .models import (
    Administrator,
    AppSecret,
    AuditEvent,
    AutomationEvent,
    AutomationRun,
    BackupDestinationCheck,
    BackupRecord,
    DiagnosticCapture,
    LoginSession,
    MetricSample,
    PerformanceSample,
    Profile,
    Schedule,
)
from .modpacks import (
    MAX_MRPACK_BYTES,
    ModpackError,
    fetch_mrpack,
    install_modpack,
    search_modpacks,
)
from .modrinth import (
    ModrinthError,
    plan_install,
)
from .modrinth import (
    check_updates as modrinth_check_updates,
)
from .modrinth import (
    list_categories as modrinth_categories,
)
from .modrinth import (
    list_project_versions as modrinth_versions,
)
from .modrinth import search as modrinth_search
from .overview import (
    PublicIpDiscovery,
    join_details,
    minecraft_status,
    minecraft_status_probe,
    read_properties,
    strict_world_size,
    world_size,
)
from .performance import (
    PERFORMANCE_SAMPLING_PERIOD_SECONDS,
    PERFORMANCE_SOURCE,
    MsptValues,
    TpsValues,
    parse_paper_performance,
    performance_capable,
)
from .player_pack_exports import (
    PlayerPackExportError,
    PlayerPackExportResult,
    build_player_mrpack,
)
from .player_sessions import (
    JOIN_PATTERN,
    LEAVE_PATTERN,
    record_log_line,
    summarize_sessions,
)
from .process import InvalidTransition, LogEvent, ProcessManager
from .provisioning import (
    DIRECTORY_PATTERN,
    USER_AGENT,
    ProvisionError,
    download_verified_file,
    list_versions,
    provision_profile,
    resolve_plan,
)
from .retention import enforce_retention
from .safe_start import (
    SafeStartError,
    cleanup_reviewed_batches,
    cleanup_validation_workspaces,
    delete_reviewed_batch,
    identify_reviewed_batch,
    load_reviewed_batch,
    plan_safe_test_start,
    run_safe_test_start,
    save_reviewed_batch,
)
from .scheduler import Scheduler, automation_steps, next_executions, parse_weekdays
from .schemas import (
    PROJECT_ID_PATTERN,
    AutomationEventRequest,
    AutomationRunRequest,
    BackupPolicyRequest,
    CleanupApplyRequest,
    CommandRequest,
    Credentials,
    CurseForgeKeyRequest,
    DiagnosticCaptureRequest,
    EulaRequest,
    FileEditRequest,
    FileRenameRequest,
    ImportRequest,
    ImportUploadFinish,
    ImportUploadStart,
    InstallRequest,
    MinecraftVersionRequest,
    ModConfigUpdateRequest,
    ModpackInstallRequest,
    NotificationPreferencesRequest,
    PlayerActionRequest,
    ProfileCreate,
    ProfileDeleteRequest,
    ProvisionRequest,
    RawSettingsUpdateRequest,
    SafeTestStartRequest,
    ScheduleRequest,
    ServerUpgradeRequest,
    SettingsUpdateRequest,
    StartRequest,
    ToggleAllRequest,
    ToggleRequest,
    UpdateRequest,
    UpdateReviewRequest,
)
from .security import (
    SESSION_COOKIE,
    LoginLimiter,
    PasswordHashError,
    authenticate_request,
    create_session,
    digest,
    hash_password,
    require_mutation_security,
    verify_password,
)
from .server_files import (
    STOPPED_REQUIRED_CATEGORIES,
    FileConflictError,
    apply_file_edit,
    build_roster,
    delete_file,
    extract_archive_into,
    list_category,
    preview_file_edit,
    read_file_content,
    read_players,
    read_settings,
    rename_file,
    resolve_download_path,
    resolve_upload_target,
    roster_names,
)
from .server_settings import (
    SettingsConflictError,
    SettingsValidationError,
    apply_raw_settings,
    apply_settings_update,
    preview_raw_settings,
    preview_settings_update,
    read_raw_settings,
)
from .server_upgrades import UpgradeContext, UpgradeReview
from .server_upgrades import (
    review as review_upgrades,
)
from .shared_map import (
    SharedMapError,
    apply_low_resource_profile,
    local_health_url,
    read_shared_map,
)
from .troubleshooting import (
    TroubleshootingContext,
    TroubleshootingRepairRequest,
    TroubleshootingRequest,
)
from .troubleshooting import (
    assess as assess_troubleshooting,
)
from .troubleshooting import (
    catalog as troubleshooting_catalog,
)
from .upgrade_ops import (
    UpgradeOperationError,
    active_launch_file,
    create_upgrade_staging,
    promote_launch_upgrade,
    rollback_launch_upgrade,
)
from .world_care import (
    CleanupTarget,
    check_backup_destination,
    cleanup_candidates,
    disk_payload,
    recovery_snapshot_entries,
    remove_cleanup_targets,
    tree_size,
)

log = logging.getLogger("blockstead.api")


def error(status_code: int, code: str, message: str, recovery: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    if recovery:
        body["error"]["recovery"] = recovery  # type: ignore[index]
    return JSONResponse(status_code=status_code, content=body)


@dataclass(frozen=True)
class ReviewedCleanupPlan:
    """A short-lived exact cleanup contract retained only in this process."""

    id: str
    profile_id: str
    created_at: datetime
    expires_at: datetime
    targets: tuple[CleanupTarget, ...]
    verified_backup_id: str


def resolve_static_dir(configured: Path | None = None) -> Path | None:
    """Locate the built dashboard in both the source checkout and an installed release.

    Installing the backend puts this module in the virtual environment's site-packages,
    so a path relative to it no longer reaches the frontend the installer copies beside
    that environment. blockstead.service runs from the application directory, which is
    what makes the working-directory candidate reach it.
    """
    candidates = [] if configured is None else [configured]
    candidates += [
        Path(__file__).parents[3] / "frontend" / "dist",
        Path.cwd() / "frontend" / "dist",
    ]
    return next((path for path in candidates if path.is_dir()), None)


def remove_readonly(function: Callable[..., object], path: str, error: BaseException) -> None:
    """Retry a tree removal after making a read-only entry writable.

    Imported Minecraft folders can legitimately contain read-only files, especially
    after being copied from Windows media. The target tree is validated separately
    before this callback is ever used.
    """

    if not isinstance(error, PermissionError):
        raise error
    target = Path(path)
    if sys.platform != "win32" or target.is_symlink():
        raise error
    target.chmod(target.stat().st_mode | stat.S_IWRITE)
    function(path)


class SpaStaticFiles(StaticFiles):
    """Serve the built frontend, letting the browser router own unknown page paths."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            unknown_page = (
                exc.status_code == 404
                and not path.startswith("api")
                and scope.get("method") in {"GET", "HEAD"}
            )
            if not unknown_page:
                raise
            return await super().get_response("index.html", scope)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    config.prepare()
    diagnostics = attach_logging(config.data_dir)
    factory = create_session_factory(config.data_dir / "blockstead.db")
    manager = ProcessManager()
    limiter = LoginLimiter()
    psutil.cpu_percent(interval=None)  # prime so later non-blocking samples are meaningful

    http_client = httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
    )
    public_ip_discovery = PublicIpDiscovery(http_client)

    metrics_task: asyncio.Task[None] | None = None
    update_task: asyncio.Task[None] | None = None
    player_session_task: asyncio.Task[None] | None = None
    update_wakeup = asyncio.Event()
    update_lock = asyncio.Lock()
    performance_lock = asyncio.Lock()

    def record_player_session_line(profile_id: str, line: str) -> None:
        with factory() as db:
            record_log_line(db, profile_id, line, datetime.now(timezone.utc))  # noqa: UP017
            db.commit()

    async def track_player_sessions(event: LogEvent) -> None:
        # A player join/leave is a small fraction of server log lines; check the
        # cheap regex before paying for a thread hop and a database write.
        if event.profile_id is None:
            return
        if not (JOIN_PATTERN.search(event.line) or LEAVE_PATTERN.search(event.line)):
            return
        await asyncio.to_thread(record_player_session_line, event.profile_id, event.line)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal metrics_task, update_task, player_session_task
        engine = factory.kw["bind"]
        Base.metadata.create_all(engine)
        with factory() as db:
            interrupted = db.scalars(
                select(BackupRecord).where(BackupRecord.status == "in_progress")
            ).all()
            for record in interrupted:
                record.status = "failed"
                record.result = "Blockstead stopped before this backup completed."
                record.completed_at = datetime.now(timezone.utc)  # noqa: UP017
            helper_result = updates.read_helper_status(config.update_status_file)
            admin_id = db.scalar(select(Administrator.id).order_by(Administrator.created_at))
            if helper_result is not None and helper_result.final and admin_id is not None:
                marker = f"Update {helper_result.commit}: {helper_result.detail}"
                recorded = db.scalar(
                    select(AuditEvent.id).where(
                        AuditEvent.category == "update_install",
                        AuditEvent.safe_detail == marker,
                    )
                )
                if recorded is None:
                    db.add(
                        AuditEvent(
                            admin_id=admin_id,
                            category="update_install",
                            result=("success" if helper_result.state == "succeeded" else "failed"),
                            safe_detail=marker,
                            created_at=helper_result.at,
                        )
                    )
            for profile in db.scalars(select(Profile)).all():
                try:
                    directory = canonical_child(Path(profile.server_directory), config.server_root)
                    cleanup_validation_workspaces(directory)
                    info = DISTRIBUTIONS.get(profile.distribution)
                    if info is not None and info.extension_directory is not None:
                        cleanup_reviewed_batches(directory / info.extension_directory)
                except (OSError, ValueError, SafeStartError):
                    log.warning(
                        "Could not clean stale loadout validation data for profile %s.",
                        profile.id,
                    )
            db.commit()
        metrics_task = asyncio.create_task(metrics_loop())
        player_session_task = asyncio.create_task(manager.subscribe(track_player_sessions))
        # A first-ever start has nothing to announce, so the build that is
        # already running is recorded quietly. Anything different arriving later
        # is a real update and is announced once the owner sees it.
        if updates.read_state(config.data_dir).acknowledged_commit is None:
            updates.acknowledge(config.data_dir, installed_build)
        update_state = updates.read_state(config.data_dir)
        if update_state.resume_profile_id is not None:
            # Resolve an interrupted or completed handoff before scheduled
            # starts can claim the single managed process for another profile.
            await resume_server_after_update()
            update_state = updates.read_state(config.data_dir)
        if update_checks_run_here() or update_state.resume_profile_id is not None:
            update_task = asyncio.create_task(update_loop())
        scheduler.begin()
        log.info(
            "Blockstead %s started; dashboard bound to %s:%s",
            installed_build.label,
            config.bind_host,
            config.port,
        )
        yield
        for task in (metrics_task, update_task, player_session_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        metrics_task = None
        update_task = None
        player_session_task = None
        await scheduler.close()
        await manager.close()
        await http_client.aclose()

    app = FastAPI(title="Blockstead API", version=__version__, lifespan=lifespan)
    app.state.settings = config
    app.state.session_factory = factory
    app.state.process_manager = manager
    app.state.diagnostics = diagnostics
    app.state.active_profile_id = None
    app.state.update_handoff_active = False
    app.state.update_waiting_for_critical_operation = False
    app.state.update_check_failures = 0
    app.state.websocket_auth_recheck_seconds = 5.0
    app.state.public_ip_discovery = public_ip_discovery
    app.state.minecraft_status_probes = {}
    # Profiles with a restore in flight; starting or backing up one is refused.
    restoring_profiles: set[str] = set()
    # Profiles with an archive extraction in flight; a second concurrent
    # extraction for the same profile is refused rather than interleaved.
    extracting_profiles: set[str] = set()
    # Profiles with a recovery drill in flight; drills use private staging and
    # never mutate the live server folder.
    recovery_drill_profiles: set[str] = set()
    # One Spark profile at a time per server avoids stopping a capture the
    # owner started elsewhere through the console.
    diagnostic_capture_profiles: set[str] = set()
    # Cleanup plans expire quickly and contain exact private-data fingerprints.
    reviewed_cleanup_plans: dict[str, ReviewedCleanupPlan] = {}
    # Long-running world mutations must finish before the service can hand an
    # update to the root helper. Tokens make concurrent backups independently
    # visible without holding the update lock for their full duration.
    critical_update_operations: set[str] = set()

    def remember_status_probe(profile_id: str, probe: dict[str, object]) -> None:
        """Retain one privacy-safe probe result so a post-stop report keeps the evidence."""

        app.state.minecraft_status_probes[profile_id] = {
            "outcome": probe.get("outcome", "unknown"),
            "detail": probe.get("detail", "No probe detail was recorded."),
            "tcp_connected": probe.get("tcp_connected"),
            "checked_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
        }

    def collect_metric_sample(profile: Profile, *, include_process: bool) -> MetricSample:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(config.data_dir))
        process_memory: int | None = None
        pid = manager.snapshot()["pid"] if include_process else None
        if isinstance(pid, int):
            try:
                process_memory = psutil.Process(pid).memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            directory = canonical_child(Path(profile.server_directory), config.server_root)
            size = world_size(directory)
        except (ValueError, OSError):
            size = None
        return MetricSample(
            profile_id=profile.id,
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=memory.percent,
            disk_percent=disk.percent,
            process_memory_bytes=process_memory,
            world_size_bytes=size,
        )

    def sample_active_profile() -> None:
        profile_id = app.state.active_profile_id
        if not isinstance(profile_id, str):
            return
        with factory() as db:
            profile = db.get(Profile, profile_id)
            if profile is None:
                return
            db.add(collect_metric_sample(profile, include_process=True))
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)  # noqa: UP017
            db.execute(delete(MetricSample).where(MetricSample.created_at < cutoff))
            db.commit()

    async def sample_performance(profile: Profile) -> None:
        """Ask a supported Paper server for bounded tick evidence at most once a minute."""

        if not performance_capable(profile.distribution):
            return
        snapshot = manager.snapshot()
        state = str(snapshot["state"])
        if state.startswith("ProcessState."):
            state = state.removeprefix("ProcessState.")
        if app.state.active_profile_id != profile.id or state != "RUNNING":
            return
        async with performance_lock:
            with factory() as db:
                latest = db.scalar(
                    select(PerformanceSample)
                    .where(PerformanceSample.profile_id == profile.id)
                    .order_by(PerformanceSample.created_at.desc())
                    .limit(1)
                )
                latest_at = latest.created_at if latest is not None else None
            now = datetime.now(timezone.utc)  # noqa: UP017
            if latest_at is not None:
                if latest_at.tzinfo is None:
                    latest_at = latest_at.replace(tzinfo=timezone.utc)  # noqa: UP017
                if now - latest_at < timedelta(seconds=50):
                    return

            before = manager.logs()[-1].sequence if manager.logs() else 0
            tps: TpsValues | None = None
            mspt: MsptValues | None = None
            detail = (
                "Paper performance commands were sent, but the server did not return "
                "labelled TPS or MSPT output within the bounded wait."
            )
            try:
                await manager.command("tps")
                await manager.command("mspt")
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    lines = [
                        event.line
                        for event in manager.logs()
                        if event.sequence > before and event.profile_id == profile.id
                    ]
                    tps, mspt = parse_paper_performance(lines)
                    if tps is not None and mspt is not None:
                        break
                    await asyncio.sleep(0.05)
                if tps is not None and mspt is not None:
                    detail = "Paper returned labelled TPS and MSPT evidence."
                elif tps is not None or mspt is not None:
                    detail = (
                        "Paper returned only part of the expected performance evidence; "
                        "the missing value is left unavailable."
                    )
            except (InvalidTransition, OSError, ValueError):
                detail = (
                    "Paper performance sampling was unavailable while the server changed state."
                )

            with factory() as db:
                db.add(
                    PerformanceSample(
                        profile_id=profile.id,
                        source=PERFORMANCE_SOURCE,
                        sampling_period_seconds=PERFORMANCE_SAMPLING_PERIOD_SECONDS,
                        tps_one_minute=tps.get("one_minute") if tps else None,
                        tps_five_minutes=tps.get("five_minutes") if tps else None,
                        tps_fifteen_minutes=tps.get("fifteen_minutes") if tps else None,
                        mspt_five_seconds=mspt.get("five_seconds") if mspt else None,
                        mspt_ten_seconds=mspt.get("ten_seconds") if mspt else None,
                        mspt_sixty_seconds=mspt.get("sixty_seconds") if mspt else None,
                        detail=detail,
                        created_at=now,
                    )
                )
                cutoff = now - timedelta(days=7)
                db.execute(delete(PerformanceSample).where(PerformanceSample.created_at < cutoff))
                db.commit()

    last_observed_state = manager.snapshot()["state"]

    async def metrics_loop() -> None:
        nonlocal last_observed_state
        while True:
            try:
                await asyncio.to_thread(sample_active_profile)
                active_id = app.state.active_profile_id
                if isinstance(active_id, str):
                    with factory() as db:
                        performance_profile = db.get(Profile, active_id)
                    if performance_profile is not None:
                        await sample_performance(performance_profile)
                state = manager.snapshot()["state"]
                if state == "CRASHED" and last_observed_state != "CRASHED":
                    with factory() as db:
                        admin_id = db.scalar(
                            select(Administrator.id).order_by(Administrator.created_at)
                        )
                        if admin_id is not None:
                            db.add(
                                AuditEvent(
                                    admin_id=admin_id,
                                    profile_id=app.state.active_profile_id,
                                    category="server_crash",
                                    result="failed",
                                    safe_detail=str(manager.snapshot()["reason"]),
                                )
                            )
                            db.commit()
                last_observed_state = state
            except Exception:
                log.exception("Could not record an overview metric sample")
            await asyncio.sleep(60)

    def get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    Db = Annotated[Session, Depends(get_db)]

    async def start_profile(profile: Profile, mode: str = "normal") -> str:
        """Start one profile after its caller has acquired update_lock."""
        arguments, cwd, label = launch_spec(profile, mode)
        await manager.start(arguments, cwd=cwd, label=label, owner=profile.id)
        app.state.active_profile_id = profile.id
        return label

    async def scheduled_start(profile: Profile) -> None:
        async with update_lock:
            if update_install_in_progress():
                raise InvalidTransition(
                    "Blockstead is being updated. The server can start when it finishes."
                )
            await start_profile(profile)

    async def begin_critical_update_operation(kind: str) -> str:
        async with update_lock:
            if update_install_in_progress():
                raise InvalidTransition(
                    "Blockstead is being updated. Try this operation after it finishes."
                )
            token = f"{kind}:{secrets.token_hex(16)}"
            critical_update_operations.add(token)
            return token

    def end_critical_update_operation(token: str) -> None:
        critical_update_operations.discard(token)
        update_wakeup.set()

    scheduler = Scheduler(
        factory,
        manager,
        scheduled_start,
        config.data_dir,
        config.server_root,
        begin_critical_operation=begin_critical_update_operation,
        end_critical_operation=end_critical_update_operation,
    )

    # Blockstead follows a branch rather than tagged releases, so the commit the
    # installer stamped is what says whether this copy is behind.
    installed_build = updates.read_build(__version__, build_file=config.update_build_file)
    app.state.installed_build = installed_build
    app.state.latest_commit = None
    app.state.update_decision = updates.Decision.CURRENT

    async def players_online_now() -> int | None:
        """How many people are on the running server, or None if unknowable."""
        profile_id = app.state.active_profile_id
        if profile_id is None:
            return None
        with factory() as db:
            profile = db.get(Profile, profile_id)
            if profile is None:
                return None
            return await scheduler.online_players(profile)

    def helper_status() -> updates.HelperStatus | None:
        return updates.read_helper_status(config.update_status_file)

    def critical_update_operation_in_progress() -> bool:
        if critical_update_operations or restoring_profiles:
            return True
        with factory() as db:
            pending = db.scalar(
                select(func.count())
                .select_from(BackupRecord)
                .where(BackupRecord.status == "in_progress")
            )
        return bool(pending)

    def update_install_in_progress() -> bool:
        return bool(app.state.update_handoff_active) or updates.install_in_progress(
            config.data_dir,
            config.update_status_file,
            max_age=timedelta(minutes=config.update_status_max_age_minutes),
            installed_commit=installed_build.commit,
        )

    def update_status() -> dict[str, object]:
        state = updates.read_state(config.data_dir)
        latest = app.state.latest_commit
        status = helper_status()
        return {
            "build": installed_build.payload(),
            "automatic": config.update_auto,
            "supported": updates.update_capable(),
            "decision": app.state.update_decision.value,
            "latest": latest.payload() if latest else None,
            "checked_at": state.last_checked_at.isoformat() if state.last_checked_at else None,
            "error": state.last_error,
            "installing": update_install_in_progress(),
            "last_result": status.payload() if status else None,
            "announcement": updates.announcement(installed_build, state),
        }

    def queue_update(
        latest: updates.RemoteCommit,
        state: updates.State,
        *,
        resume_profile_id: str | None = None,
    ) -> updates.State:
        """Persist all recovery context before making the helper request visible."""
        requested_at = datetime.now(timezone.utc)  # noqa: UP017
        requested_attempt = secrets.token_hex(16)
        queued = replace(
            state,
            requested_commit=latest.commit,
            requested_summary=latest.summary,
            requested_at=requested_at,
            requested_attempt=requested_attempt,
            resume_profile_id=resume_profile_id,
            resume_commit=latest.commit if resume_profile_id else None,
        )
        app.state.update_handoff_active = True
        try:
            updates.write_state(config.data_dir, queued)
            updates.request_install(
                config.data_dir,
                latest.commit,
                attempt=requested_attempt,
                requested_at=requested_at,
            )
        except OSError:
            # If making the request visible fails after an empty server was
            # stopped, mark the attempt as never handed off. The monitor can
            # then resume that server without waiting for a helper status that
            # will never arrive.
            try:
                updates.write_state(
                    config.data_dir,
                    replace(queued, requested_at=None, requested_attempt=None),
                )
            except OSError:
                log.exception("Could not persist update handoff recovery state")
            raise
        finally:
            app.state.update_handoff_active = False
            update_wakeup.set()
        return queued

    async def resume_server_after_update() -> bool:
        """Resume an empty server stopped solely to let the helper update.

        The helper starts Blockstead before it writes its final status, because
        the installer first waits for this API's health endpoint. Consequently
        this must run in the background and poll instead of blocking startup.
        """
        async with update_lock:
            state = updates.read_state(config.data_dir)
            if state.resume_profile_id is None or state.resume_commit is None:
                return False
            request_pending = updates.pending_request(config.data_dir) is not None
            if request_pending:
                return False
            status = helper_status()
            if state.requested_at is not None and not updates.status_completes_request(
                state,
                status,
                installed_commit=installed_build.commit,
                request_pending=request_pending,
            ):
                return False

            profile_id = state.resume_profile_id
            cleared = replace(
                state,
                requested_at=None,
                requested_attempt=None,
                resume_profile_id=None,
                resume_commit=None,
            )
            snapshot = manager.snapshot()
            if snapshot["state"] in {"RUNNING", "STARTING", "STOPPING", "DEGRADED"}:
                running_profile_id = app.state.active_profile_id
                detail = (
                    None
                    if running_profile_id == profile_id
                    else "The server was not resumed because another profile is running."
                )
                updates.write_state(
                    config.data_dir,
                    replace(cleared, last_error=detail or state.last_error),
                )
                return detail is None

            with factory() as db:
                profile = db.get(Profile, profile_id)
                if profile is None:
                    updates.write_state(
                        config.data_dir,
                        replace(
                            cleared,
                            last_error=(
                                "Blockstead finished updating, but the server profile "
                                "that was running no longer exists."
                            ),
                        ),
                    )
                    return False
                try:
                    # update_lock is already held here; use the coordinated
                    # primitive directly instead of recursively taking it.
                    await start_profile(profile)
                except Exception:
                    log.exception("Could not resume profile %s after the update", profile_id)
                    updates.write_state(
                        config.data_dir,
                        replace(
                            cleared,
                            last_error=(
                                "Blockstead finished updating, but it could not restart "
                                "the server automatically. Start it from the dashboard."
                            ),
                        ),
                    )
                    return False

            updates.write_state(config.data_dir, cleared)
            log.info("Resumed profile %s after the update helper finished.", profile_id)
            return True

    async def _check_for_update(*, install: bool = True) -> dict[str, object]:
        """Look at GitHub and, when the moment is polite, ask for the install."""
        if update_install_in_progress():
            # Do not replace a request or refetch the channel while the helper
            # is already downloading/installing this (or another) commit.
            app.state.update_decision = updates.Decision.INSTALL
            return update_status()
        if critical_update_operation_in_progress():
            # Backups and restores mutate owner data for much longer than one
            # event-loop turn. Their completion wakes the updater immediately.
            app.state.update_waiting_for_critical_operation = True
            return update_status()
        app.state.update_waiting_for_critical_operation = False

        state = updates.read_state(config.data_dir)
        now = datetime.now(timezone.utc)  # noqa: UP017
        try:
            latest = await updates.fetch_latest(
                http_client,
                config.update_repo,
                config.update_branch,
                config.update_manifest_url,
            )
        except (httpx.HTTPError, ValueError) as exc:
            app.state.update_check_failures += 1
            log.warning("Blockstead could not check for updates: %s", exc)
            updates.write_state(
                config.data_dir,
                replace(
                    state,
                    last_checked_at=now,
                    last_error="Blockstead could not reach GitHub to check for updates.",
                ),
            )
            return update_status()

        app.state.update_check_failures = 0
        app.state.latest_commit = latest
        # An installation that was never stamped with a commit cannot be
        # compared against anything, so the first successful check adopts what
        # is current instead of reinstalling over a copy that may already match.
        if installed_build.commit is None and state.baseline_commit is None:
            state = replace(state, baseline_commit=latest.commit)

        snapshot = manager.snapshot()
        running = snapshot["state"] in {"RUNNING", "STARTING", "STOPPING", "DEGRADED"}
        decision = updates.decide(
            behind=updates.is_behind(installed_build, latest, baseline=state.baseline_commit),
            auto=config.update_auto,
            capable=updates.update_capable(),
            server_running=running,
            players_online=await players_online_now() if running else None,
            failed=updates.failed_commit_suppressed(helper_status(), latest.commit, now=now),
        )
        state = replace(state, last_checked_at=now, last_error=None)

        if install and decision is updates.Decision.STOP_SERVER_FIRST:
            # Nobody is playing, and the installer refuses to run while the
            # service still owns a Minecraft process, so close it down politely.
            log.info("Stopping the empty Minecraft server so Blockstead can update.")
            resume_profile_id = app.state.active_profile_id
            if not isinstance(resume_profile_id, str):
                decision = updates.Decision.WAITING_FOR_PLAYERS
            else:
                # Write the recovery intent before stopping Java. If this
                # process dies between the graceful stop and helper request,
                # the next start sees requested_at=None and brings it back.
                state = replace(
                    state,
                    requested_at=None,
                    requested_attempt=None,
                    resume_profile_id=resume_profile_id,
                    resume_commit=latest.commit,
                )
                updates.write_state(config.data_dir, state)
                app.state.update_handoff_active = True
                try:
                    stopped = await manager.stop(timeout=60.0)
                except (InvalidTransition, OSError):
                    stopped = False
                except Exception:
                    app.state.update_handoff_active = False
                    updates.write_state(
                        config.data_dir,
                        replace(state, resume_profile_id=None, resume_commit=None),
                    )
                    raise
                if stopped:
                    app.state.active_profile_id = None
                    decision = updates.Decision.INSTALL
                else:
                    app.state.update_handoff_active = False
                    decision = updates.Decision.WAITING_FOR_PLAYERS
                    state = replace(state, resume_profile_id=None, resume_commit=None)
                    log.warning("The Minecraft server did not stop, so the update waits.")

        if install and decision is updates.Decision.INSTALL:
            state = queue_update(
                latest,
                state,
                resume_profile_id=(
                    state.resume_profile_id if state.resume_commit == latest.commit else None
                ),
            )

        app.state.update_decision = decision
        updates.write_state(config.data_dir, state)
        return update_status()

    async def check_for_update(*, install: bool = True) -> dict[str, object]:
        async with update_lock:
            return await _check_for_update(install=install)

    def next_update_delay() -> float:
        state = updates.read_state(config.data_dir)
        if update_install_in_progress() or state.resume_profile_id is not None:
            return config.update_status_poll_seconds
        if app.state.update_waiting_for_critical_operation:
            return config.update_wait_minutes * 60
        if app.state.update_decision is updates.Decision.WAITING_FOR_PLAYERS:
            return config.update_wait_minutes * 60
        if app.state.update_check_failures:
            # A host can start before DNS or Wi-Fi is ready. Retry promptly, then
            # back off to the normal cadence if the network remains unavailable.
            retry_number = min(int(app.state.update_check_failures) - 1, 6)
            return min(
                config.update_check_hours * 3600,
                config.update_wait_minutes * 60 * (2**retry_number),
            )
        status = helper_status()
        if (
            app.state.update_decision is updates.Decision.INSTALL
            and updates.status_completes_request(
                state,
                status,
                installed_commit=installed_build.commit,
                request_pending=updates.pending_request(config.data_dir) is not None,
            )
        ):
            # Reconcile a final note written by the helper after the previous
            # loop iteration inspected its request or active status.
            return config.update_status_poll_seconds
        retry_delay = updates.retry_delay_seconds(
            status,
            now=datetime.now(timezone.utc),  # noqa: UP017
            normal_seconds=config.update_check_hours * 3600,
            minimum_seconds=config.update_wait_minutes * 60,
        )
        if retry_delay is not None:
            return retry_delay
        return config.update_check_hours * 3600

    async def update_loop() -> None:
        while True:
            try:
                await resume_server_after_update()
                if update_checks_run_here():
                    await check_for_update()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("The Blockstead update check stopped unexpectedly.")
            state = updates.read_state(config.data_dir)
            if not update_checks_run_here() and state.resume_profile_id is None:
                return
            try:
                await asyncio.wait_for(update_wakeup.wait(), timeout=next_update_delay())
            except TimeoutError:
                pass
            finally:
                update_wakeup.clear()

    def update_checks_run_here() -> bool:
        """Only an installation that could act on an update checks by itself.

        A development checkout, a test run, and a Docker image have no
        privileged helper and update by other means, so none of them should
        reach out to GitHub on their own. Asking on purpose still works
        everywhere through the check endpoint.
        """
        return config.update_auto and updates.update_capable()

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self' ws: wss:; img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'"
        )
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else "no-cache"
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error(
            422,
            "REQUEST_INVALID",
            "Some submitted information was invalid.",
            "Review the highlighted fields and try again.",
        )

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        code = {
            401: "AUTHENTICATION_REQUIRED",
            403: "REQUEST_FORBIDDEN",
            404: "NOT_FOUND",
            409: "OPERATION_CONFLICT",
            429: "LOGIN_RATE_LIMITED",
        }.get(exc.status_code, "REQUEST_FAILED")
        return error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled request error", exc_info=exc)
        return error(
            500,
            "INTERNAL_ERROR",
            "Blockstead could not complete that request.",
            "Try again. If it continues, review the application log.",
        )

    def current(request: Request, db: Session) -> tuple[Administrator, LoginSession]:
        return authenticate_request(request, db)

    def mutation(request: Request, db: Session) -> Administrator:
        admin, session = current(request, db)
        require_mutation_security(request, session, config.origins)
        return admin

    def backup_payload(record: BackupRecord) -> dict[str, object]:
        def timestamp(value: datetime) -> str:
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)  # noqa: UP017
            return value.astimezone(timezone.utc).isoformat()  # noqa: UP017

        archive_available = bool(
            record.status == "completed"
            and record.file_name
            and (config.data_dir / "backups" / record.profile_id / record.file_name).is_file()
        )
        return {
            "id": record.id,
            "profile_id": record.profile_id,
            "status": record.status,
            "method": record.method,
            "trigger": record.trigger,
            "file_name": record.file_name,
            "size_bytes": record.size_bytes,
            "duration_ms": record.duration_ms,
            "sha256": record.sha256,
            "included_paths": json.loads(record.included_paths) if record.included_paths else [],
            "archive_available": archive_available,
            "result": record.result,
            "created_at": timestamp(record.created_at),
            "completed_at": timestamp(record.completed_at) if record.completed_at else None,
        }

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": installed_build.version,
            "commit": installed_build.commit,
            "short_commit": installed_build.short_commit,
        }

    @app.get("/api/v1/setup/status")
    def setup_status(db: Db) -> dict[str, bool]:
        return {
            "needs_setup": (db.scalar(select(func.count()).select_from(Administrator)) or 0) == 0
        }

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE,
            token,
            httponly=True,
            secure=config.secure_cookies,
            samesite="strict",
            max_age=config.session_hours * 3600,
            path="/",
        )

    @app.post("/api/v1/setup/admin", status_code=201)
    def setup_admin(
        payload: Credentials, request: Request, response: Response, db: Db
    ) -> dict[str, str]:
        if request.headers.get("origin") not in config.origins:
            raise HTTPException(403, "This request came from an untrusted page.")
        if (db.scalar(select(func.count()).select_from(Administrator)) or 0) != 0:
            raise HTTPException(409, "An administrator already exists.")
        admin = Administrator(
            username=payload.username, password_hash=hash_password(payload.password)
        )
        db.add(admin)
        db.commit()
        token, csrf = create_session(db, admin, config.session_hours)
        set_session_cookie(response, token)
        return {"username": admin.username, "csrf_token": csrf}

    @app.post("/api/v1/auth/login")
    def login(payload: Credentials, request: Request, response: Response, db: Db) -> dict[str, str]:
        if request.headers.get("origin") not in config.origins:
            raise HTTPException(403, "This request came from an untrusted page.")
        client_host = request.client.host if request.client else "unknown"
        key = f"{client_host}:{payload.username.casefold()}"
        admin = db.scalar(
            select(Administrator).where(
                func.lower(Administrator.username) == payload.username.lower()
            )
        )
        try:
            password_valid = admin is not None and verify_password(
                admin.password_hash, payload.password
            )
        except PasswordHashError as exc:
            log.error("The stored administrator password hash could not be verified")
            raise HTTPException(
                500,
                "The stored administrator password could not be read. Use the local password "
                "recovery command shown on this page.",
            ) from exc
        if not password_valid:
            limiter.fail(key)
            raise HTTPException(401, "The username or password was not accepted.")
        assert admin is not None
        limiter.clear(key)
        token, csrf = create_session(db, admin, config.session_hours)
        set_session_cookie(response, token)
        return {"username": admin.username, "csrf_token": csrf}

    @app.post("/api/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response, db: Db) -> None:
        _, session = current(request, db)
        require_mutation_security(request, session, config.origins)
        db.delete(session)
        db.commit()
        response.delete_cookie(SESSION_COOKIE, path="/")

    @app.get("/api/v1/auth/me")
    def me(request: Request, db: Db) -> dict[str, str]:
        admin, _ = current(request, db)
        return {"username": admin.username}

    def scan_error(exc: Exception) -> HTTPException:
        """Turn folder-scan failures into plain-language guidance, never raw errno text."""
        if isinstance(exc, PermissionError):
            return HTTPException(
                400,
                "Blockstead is not allowed to read that folder — home folders are "
                "private to your Linux account. Use the Import section's "
                "'From this computer' option to upload the folder instead.",
            )
        if isinstance(exc, FileNotFoundError):
            return HTTPException(
                400,
                "That folder was not found on this computer. Check the spelling, or "
                "use the Import section's 'From this computer' option to upload it.",
            )
        if isinstance(exc, ValueError):
            return HTTPException(400, str(exc))
        return HTTPException(400, "That folder could not be read.")

    @app.post("/api/v1/imports/scan")
    def import_scan(payload: ImportRequest, request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        try:
            return scan_server(Path(payload.path), config.server_root).model_dump()
        except (ValueError, OSError) as exc:
            raise scan_error(exc) from exc

    def upload_staging(upload_id: str) -> Path:
        staging = config.server_root / f"{UPLOAD_PREFIX}{upload_id}"
        if len(upload_id) != 32 or not upload_id.isalnum() or not staging.is_dir():
            raise HTTPException(404, "That upload was not found or has expired.")
        return staging

    def abandon_upload(staging: Path) -> None:
        shutil.rmtree(staging, ignore_errors=True)

    @app.post("/api/v1/imports/uploads", status_code=201)
    def import_upload_start(payload: ImportUploadStart, request: Request, db: Db) -> dict[str, str]:
        mutation(request, db)
        purge_stale_uploads(config.server_root)
        if not DIRECTORY_PATTERN.match(payload.directory_name):
            raise HTTPException(
                400,
                "Server folder names use lowercase letters, digits, dashes, and "
                "underscores, and start with a letter or digit.",
            )
        if (config.server_root / payload.directory_name).exists():
            raise HTTPException(
                409,
                f"A server folder named {payload.directory_name} already exists. "
                "Choose a different name.",
            )
        token = secrets.token_hex(16)
        (config.server_root / f"{UPLOAD_PREFIX}{token}").mkdir(mode=0o755)
        return {"upload_id": token}

    @app.post("/api/v1/imports/uploads/{upload_id}/files")
    async def import_upload_files(
        upload_id: str, files: list[UploadFile], request: Request, db: Db
    ) -> dict[str, object]:
        mutation(request, db)
        staging = upload_staging(upload_id)
        if len(files) > 1000:
            raise HTTPException(400, "Send the upload in smaller batches of files.")
        free_margin = 1 << 30
        budget = psutil.disk_usage(str(config.server_root)).free - free_margin
        written = 0
        try:
            for file in files:
                destination = staging / safe_relative_path(file.filename or "")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as output:
                    while chunk := await file.read(1 << 20):
                        written += len(chunk)
                        if written > budget:
                            raise HTTPException(
                                409,
                                "The computer does not have enough free disk space "
                                "for this server folder. Free some space and start "
                                "the import again.",
                            )
                        output.write(chunk)
        except HTTPException:
            abandon_upload(staging)
            raise
        except ValueError as exc:
            abandon_upload(staging)
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            abandon_upload(staging)
            raise HTTPException(
                409, "The uploaded files could not be written. Start the import again."
            ) from exc
        return {"upload_id": upload_id, "received_files": len(files), "received_bytes": written}

    @app.post("/api/v1/imports/uploads/{upload_id}/finish", status_code=201)
    def import_upload_finish(
        upload_id: str, payload: ImportUploadFinish, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        staging = upload_staging(upload_id)
        if not DIRECTORY_PATTERN.match(payload.directory_name):
            abandon_upload(staging)
            raise HTTPException(400, "That server folder name cannot be used.")
        if not any(staging.iterdir()):
            abandon_upload(staging)
            raise HTTPException(400, "The upload contained no files, so nothing was imported.")
        target = config.server_root / payload.directory_name
        try:
            promote_staging(staging, target)
        except ValueError as exc:
            abandon_upload(staging)
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            abandon_upload(staging)
            raise HTTPException(
                409, "The imported folder could not be moved into place. Try again."
            ) from exc
        result = scan_server(target, config.server_root)
        profile = Profile(
            name=payload.name.strip(),
            server_directory=result.canonical_path,
            distribution=result.distribution,
            minecraft_version=result.minecraft_version,
            loader_version=None,
            is_fixture=result.is_fixture,
        )
        db.add(profile)
        db.flush()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="profile_import",
                result="success",
                safe_detail=f"Imported an uploaded {result.distribution} server folder",
            )
        )
        db.commit()
        return {"id": profile.id, "name": profile.name, **result.model_dump()}

    @app.delete("/api/v1/imports/uploads/{upload_id}", status_code=204)
    def import_upload_cancel(upload_id: str, request: Request, db: Db) -> None:
        mutation(request, db)
        abandon_upload(upload_staging(upload_id))

    def refresh_profile_facts(profiles: list[Profile], db: Session) -> None:
        """Refresh safe, on-disk facts after a server has had a chance to run."""

        changed = False
        for profile in profiles:
            try:
                folder = canonical_child(Path(profile.server_directory), config.server_root)
                detected = scan_server(folder, config.server_root)
            except (ValueError, OSError):
                continue
            if detected.distribution != "unknown" and profile.distribution != detected.distribution:
                profile.distribution = detected.distribution
                changed = True
            if (
                detected.minecraft_version
                and profile.minecraft_version != detected.minecraft_version
            ):
                profile.minecraft_version = detected.minecraft_version
                changed = True
            if profile.is_fixture != detected.is_fixture:
                profile.is_fixture = detected.is_fixture
                changed = True
        if changed:
            db.commit()

    def overlapping_profiles(
        directory: Path,
        db: Session,
        *,
        exclude_profile_id: str | None = None,
    ) -> list[tuple[Profile, Path]]:
        """Find profile ownership boundaries that collide with ``directory``.

        Older releases could record the server root itself as a profile. That
        record is quarantined by ``canonical_child`` and deliberately ignored
        here so valid child profiles remain usable until the owner removes the
        bad record without deleting files.
        """

        root = config.server_root.resolve(strict=False)
        matches: list[tuple[Profile, Path]] = []
        for other in db.scalars(select(Profile)).all():
            if other.id == exclude_profile_id:
                continue
            try:
                other_directory = Path(other.server_directory).resolve(strict=False)
            except OSError:
                continue
            if other_directory == root:
                continue
            if directory_overlap(directory, other_directory):
                matches.append((other, other_directory))
        return matches

    def refuse_profile_overlap(directory: Path, db: Session) -> None:
        conflicts = overlapping_profiles(directory, db)
        if not conflicts:
            return
        conflict = conflicts[0][0]
        raise HTTPException(
            409,
            (
                f"That folder overlaps the managed server {conflict.name}. "
                "Choose a separate folder so one profile cannot change another server's files."
            ),
        )

    @app.get("/api/v1/profiles")
    def list_profiles(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        refresh_profile_facts(list(db.scalars(select(Profile)).all()), db)
        return [
            {
                "id": p.id,
                "name": p.name,
                "server_directory": p.server_directory,
                "distribution": p.distribution,
                "minecraft_version": p.minecraft_version,
                "loader_version": p.loader_version,
                "is_fixture": p.is_fixture,
            }
            for p in db.scalars(select(Profile).order_by(Profile.created_at)).all()
        ]

    @app.delete("/api/v1/profiles/{profile_id}")
    def remove_profile(
        profile_id: str, payload: ProfileDeleteRequest, request: Request, db: Db
    ) -> dict[str, object]:
        """Remove one stopped profile, optionally including its local data.

        The default only removes Blockstead's record. A folder uploaded or
        provisioned through Blockstead may contain irreplaceable world data, so
        permanent deletion requires both an explicit flag and a typed name.
        """

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That server was not found.")
        if payload.confirm_name.strip() != profile.name:
            raise HTTPException(422, "Type this server's exact name to confirm removal.")
        if app.state.active_profile_id == profile.id:
            raise HTTPException(409, "Stop this server before removing it.")
        pending_backup = db.scalar(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "in_progress",
            )
        )
        if pending_backup is not None:
            raise HTTPException(409, "Wait for the current backup to finish before removing it.")

        if payload.delete_files:
            try:
                directory = canonical_child(Path(profile.server_directory), config.server_root)
            except (ValueError, OSError) as exc:
                raise HTTPException(
                    409, "The server folder is no longer inside the allowed server root."
                ) from exc
            if overlapping_profiles(directory, db, exclude_profile_id=profile.id):
                raise HTTPException(
                    409,
                    (
                        "The server files were not deleted because this profile folder overlaps "
                        "another managed server. Remove only the Blockstead profile record and "
                        "keep the files."
                    ),
                )
            try:
                shutil.rmtree(directory, onexc=remove_readonly)
                shutil.rmtree(backup_directory(config.data_dir, profile.id), ignore_errors=True)
            except OSError as exc:
                raise HTTPException(
                    409,
                    "The server files could not be fully deleted. The profile record and local "
                    "backups were kept; inspect the server folder before retrying.",
                ) from exc

        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="profile_remove",
                result="success",
                safe_detail=(
                    f"Permanently removed {profile.name} and its local server files"
                    if payload.delete_files
                    else f"Removed {profile.name} from Blockstead while keeping its files"
                ),
            )
        )
        db.delete(profile)
        db.commit()
        return {
            "id": profile_id,
            "name": profile.name,
            "files_deleted": payload.delete_files,
            "detail": (
                "The profile, server folder, and Blockstead's local backups were deleted."
                if payload.delete_files
                else "The profile was removed; its server folder and local backups were kept."
            ),
        }

    @app.get("/api/v1/profiles/{profile_id}/backups")
    def list_backups(profile_id: str, request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        if db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        records = db.scalars(
            select(BackupRecord)
            .where(BackupRecord.profile_id == profile_id)
            .order_by(BackupRecord.created_at.desc())
            .limit(50)
        ).all()
        return [backup_payload(record) for record in records]

    @app.get("/api/v1/profiles/{profile_id}/backups/{backup_id}/download")
    def download_backup(profile_id: str, backup_id: str, request: Request, db: Db) -> FileResponse:
        current(request, db)
        record = db.get(BackupRecord, backup_id)
        if record is None or record.profile_id != profile_id:
            raise HTTPException(404, "That backup was not found for this server.")
        if record.status != "completed" or not record.file_name:
            raise HTTPException(409, "Only a completed backup can be saved elsewhere.")
        if "/" in record.file_name or "\\" in record.file_name or record.file_name.startswith("."):
            raise HTTPException(409, "This backup's archive name is not usable.")
        archive = config.data_dir / "backups" / profile_id / record.file_name
        if not archive.is_file():
            raise HTTPException(409, "This backup archive is no longer on disk.")
        return FileResponse(archive, filename=record.file_name, media_type="application/gzip")

    @app.post("/api/v1/profiles/{profile_id}/backups", status_code=201)
    async def create_backup(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        async with update_lock:
            if update_install_in_progress():
                raise HTTPException(
                    409, "Blockstead is being updated. Create the backup after it finishes."
                )
            profile = db.get(Profile, profile_id)
            if profile is None:
                raise HTTPException(404, "That profile was not found.")
            pending = db.scalar(
                select(BackupRecord).where(
                    BackupRecord.profile_id == profile_id,
                    BackupRecord.status == "in_progress",
                )
            )
            if pending is not None:
                raise HTTPException(409, "A backup is already in progress for this server.")
            if profile.id in restoring_profiles:
                raise HTTPException(
                    409, "A restore is in progress for this server. Wait for it to finish."
                )

            created_at = datetime.now(timezone.utc)  # noqa: UP017
            record = BackupRecord(profile_id=profile.id, trigger="manual", created_at=created_at)
            db.add(record)
            # The durable in-progress row is the update gate after this lock is
            # released; lifespan marks it failed if the process is interrupted.
            db.commit()
        started = time.monotonic()
        archive: BackupArchive | None = None
        failure: str | None = None
        snapshot = manager.snapshot()
        running = app.state.active_profile_id == profile.id and snapshot["state"] in {
            "RUNNING",
            "STARTING",
            "DEGRADED",
        }
        saving_suspended = False
        try:
            try:
                server_directory = canonical_child(
                    Path(profile.server_directory), config.server_root
                )
            except (ValueError, OSError) as exc:
                raise BackupError(
                    "The profile folder is no longer inside the allowed server root."
                ) from exc
            if running:
                await manager.command("save-off")
                saving_suspended = True
                await manager.command("save-all flush")
            archive = await asyncio.to_thread(
                create_backup_archive,
                profile.id,
                server_directory,
                config.data_dir,
                record.id,
                created_at,
                profile_name=profile.name,
                distribution=profile.distribution,
                minecraft_version=profile.minecraft_version,
                application_version=__version__,
                trigger="manual",
            )
        except BackupError as exc:
            failure = str(exc)
        except (InvalidTransition, ValueError):
            failure = "The server changed state before its world could be safely backed up."
        except Exception:
            log.exception("Unexpected manual backup failure for profile %s", profile.id)
            failure = "The world archive could not be completed."
        finally:
            if saving_suspended:
                try:
                    await manager.command("save-on")
                except (InvalidTransition, ValueError):
                    failure = (
                        f"{failure} " if failure else ""
                    ) + "Minecraft saving could not be re-enabled automatically."

        record.completed_at = datetime.now(timezone.utc)  # noqa: UP017
        record.duration_ms = round((time.monotonic() - started) * 1000)
        mirror_note: str | None = None
        if archive is not None:
            record.file_name = archive.file_name
            record.manifest_name = archive.manifest_name
            record.sha256 = archive.sha256
            record.included_paths = json.dumps(list(archive.included_paths))
            record.size_bytes = archive.size_bytes
            if profile.backup_redundancy_enabled:
                copied, failed = await asyncio.to_thread(
                    mirror_backup_archive,
                    config.data_dir,
                    profile.id,
                    archive,
                    [Path(value) for value in configured_backup_destinations(profile)],
                )
                if failed:
                    mirror_note = (
                        f"The primary backup succeeded, but {len(failed)} approved "
                        "destination(s) were unavailable."
                    )
                elif copied:
                    label = "destination" if len(copied) == 1 else "destinations"
                    mirror_note = f"Mirrored to {len(copied)} approved {label}."
        if failure:
            record.status = "failed"
            record.result = failure
        else:
            assert archive is not None
            record.status = "completed"
            record.result = " ".join(
                part
                for part in (
                    f"Protected {', '.join(archive.included_paths)}.",
                    mirror_note,
                )
                if part
            )
            enforce_retention(db, profile, config.data_dir)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="manual_backup",
                result="failed" if failure else "success",
                safe_detail=(
                    f"Backup failed for {profile.name}: {failure}"
                    if failure
                    else f"Created manual backup for {profile.name}"
                ),
            )
        )
        db.commit()
        update_wakeup.set()
        if failure:
            raise HTTPException(409, failure)
        return backup_payload(record)

    def restore_context(
        profile_id: str, backup_id: str, db: Session
    ) -> tuple[Profile, BackupRecord, Path]:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        record = db.get(BackupRecord, backup_id)
        if record is None or record.profile_id != profile.id:
            raise HTTPException(404, "That backup was not found for this server.")
        if record.status == "expired":
            raise HTTPException(
                409, "This backup was removed by the retention policy and cannot be restored."
            )
        if record.status != "completed" or not record.file_name or not record.manifest_name:
            raise HTTPException(409, "Only a completed backup with a manifest can be restored.")
        try:
            server_directory = canonical_child(Path(profile.server_directory), config.server_root)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "The profile folder is no longer inside the allowed server root."
            ) from exc
        return profile, record, server_directory

    def restore_blockers(profile: Profile, db: Session) -> list[str]:
        blockers: list[str] = []
        snapshot = manager.snapshot()
        if app.state.active_profile_id == profile.id and snapshot["state"] not in {
            "STOPPED",
            "CRASHED",
        }:
            blockers.append("Stop this server before restoring a backup.")
        if profile.id in restoring_profiles:
            blockers.append("A restore is already in progress for this server.")
        pending = db.scalar(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "in_progress",
            )
        )
        if pending is not None:
            blockers.append("Wait for the current backup to finish before restoring.")
        return blockers

    def recovery_drill_blockers(profile: Profile, db: Session) -> list[str]:
        blockers: list[str] = []
        if profile.id in restoring_profiles:
            blockers.append("A restore is already in progress for this server.")
        if profile.id in recovery_drill_profiles:
            blockers.append("A recovery drill is already in progress for this server.")
        pending = db.scalar(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "in_progress",
            )
        )
        if pending is not None:
            blockers.append("Wait for the current backup to finish before testing recovery.")
        return blockers

    @app.get("/api/v1/profiles/{profile_id}/backups/{backup_id}/restore-preview")
    def restore_preview(
        profile_id: str, backup_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        profile, record, server_directory = restore_context(profile_id, backup_id, db)
        assert record.file_name and record.manifest_name
        try:
            plan = plan_restore(
                config.data_dir,
                profile.id,
                record.file_name,
                record.manifest_name,
                server_directory,
                record.sha256,
            )
        except RestoreError as exc:
            raise HTTPException(409, str(exc)) from exc
        blockers = restore_blockers(profile, db)
        return {
            "backup_id": record.id,
            "verified": True,
            "sha256": plan.sha256,
            "size_bytes": plan.size_bytes,
            "included_paths": list(plan.included_paths),
            "worlds_replaced": list(plan.worlds_replaced),
            "required_bytes": plan.required_bytes,
            "available_bytes": plan.available_bytes,
            "backup_created_at": plan.created_at,
            "minecraft_version": plan.minecraft_version,
            "can_restore": not blockers,
            "blockers": blockers,
        }

    @app.post("/api/v1/profiles/{profile_id}/backups/{backup_id}/recovery-drill")
    async def recovery_drill(
        profile_id: str, backup_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile, record, server_directory = restore_context(profile_id, backup_id, db)
        async with update_lock:
            if update_install_in_progress():
                raise HTTPException(
                    409,
                    "Blockstead is being updated. Run the recovery drill after it finishes.",
                )
            blockers = recovery_drill_blockers(profile, db)
            if blockers:
                raise HTTPException(409, " ".join(blockers))
            assert record.file_name and record.manifest_name
            recovery_drill_profiles.add(profile.id)
        try:
            result = await asyncio.to_thread(
                perform_recovery_drill,
                config.data_dir,
                profile.id,
                record.file_name,
                record.manifest_name,
                server_directory,
                config.data_dir / "recovery-drills",
                record.sha256,
            )
        except RestoreError as exc:
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="backup_recovery_drill",
                    result="failed",
                    safe_detail=f"Recovery drill failed for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        finally:
            recovery_drill_profiles.discard(profile.id)
            update_wakeup.set()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="backup_recovery_drill",
                result="success",
                safe_detail=(
                    f"Verified recovery staging for {profile.name}; live worlds were unchanged"
                ),
            )
        )
        db.commit()
        return {
            "backup_id": record.id,
            "verified": True,
            "staged_paths": list(result.staged_paths),
            "staged_bytes": result.staged_bytes,
            "duration_ms": result.duration_ms,
            "result": (
                f"Verified {', '.join(result.staged_paths)} in private staging. "
                "The staging copy was removed and the live world was not changed."
            ),
        }

    @app.post("/api/v1/profiles/{profile_id}/backups/{backup_id}/restore")
    async def restore_backup(
        profile_id: str, backup_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile, record, server_directory = restore_context(profile_id, backup_id, db)
        async with update_lock:
            if update_install_in_progress():
                raise HTTPException(
                    409, "Blockstead is being updated. Restore the backup after it finishes."
                )
            blockers = restore_blockers(profile, db)
            if blockers:
                raise HTTPException(409, " ".join(blockers))
            assert record.file_name and record.manifest_name
            restoring_profiles.add(profile.id)
        try:
            result = await asyncio.to_thread(
                perform_restore,
                config.data_dir,
                profile.id,
                record.file_name,
                record.manifest_name,
                server_directory,
                datetime.now(timezone.utc),  # noqa: UP017
                record.sha256,
            )
        except RestoreError as exc:
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="backup_restore",
                    result="failed",
                    safe_detail=f"Restore failed for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        finally:
            restoring_profiles.discard(profile.id)
            update_wakeup.set()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="backup_restore",
                result="success",
                safe_detail=f"Restored a verified backup for {profile.name}",
            )
        )
        db.commit()
        return {
            "restored_paths": list(result.restored_paths),
            "preserved_paths": list(result.preserved_paths),
            "result": (
                f"Restored {', '.join(result.restored_paths)}. "
                "The replaced world folders were kept beside them "
                "until you remove them."
            ),
        }

    def configured_backup_destinations(profile: Profile) -> list[str]:
        try:
            values = json.loads(profile.backup_destinations or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return [value for value in values if isinstance(value, str)]

    def policy_payload(profile: Profile) -> dict[str, object]:
        storage_dir = backup_directory(config.data_dir, profile.id)
        return {
            "keep_count": profile.backup_keep_count,
            "keep_days": profile.backup_keep_days,
            "max_total_mb": profile.backup_max_total_mb,
            "redundancy_enabled": profile.backup_redundancy_enabled,
            "destinations": configured_backup_destinations(profile),
            "storage_path": str(storage_dir.resolve()) if storage_dir.is_dir() else None,
        }

    @app.get("/api/v1/profiles/{profile_id}/backup-policy")
    def read_backup_policy(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        return policy_payload(profile)

    @app.put("/api/v1/profiles/{profile_id}/backup-policy")
    def update_backup_policy(
        profile_id: str, payload: BackupPolicyRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        profile.backup_keep_count = payload.keep_count
        profile.backup_keep_days = payload.keep_days
        profile.backup_max_total_mb = payload.max_total_mb
        resolved_destinations: list[str] = []
        for raw in payload.destinations:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise HTTPException(422, "Backup destinations must use full folder paths.")
            try:
                resolved = path.resolve(strict=True)
            except OSError as exc:
                raise HTTPException(422, f"Backup destination is unavailable: {raw}") from exc
            if not resolved.is_dir():
                raise HTTPException(422, f"Backup destination is not a folder: {raw}")
            resolved_destinations.append(str(resolved))
        if payload.redundancy_enabled and not resolved_destinations:
            raise HTTPException(422, "Add at least one approved backup destination.")
        profile.backup_redundancy_enabled = payload.redundancy_enabled
        profile.backup_destinations = json.dumps(resolved_destinations)
        expired = enforce_retention(db, profile, config.data_dir)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="backup_policy",
                result="success",
                safe_detail=f"Updated backup retention for {profile.name}",
            )
        )
        db.commit()
        return {**policy_payload(profile), "expired_now": len(expired)}

    @app.post("/api/v1/profiles", status_code=201)
    def create_profile(payload: ProfileCreate, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        try:
            result = scan_server(
                canonical_child(Path(payload.path), config.server_root), config.server_root
            )
        except (ValueError, OSError) as exc:
            raise scan_error(exc) from exc
        refuse_profile_overlap(Path(result.canonical_path), db)
        profile = Profile(
            name=payload.name.strip(),
            server_directory=result.canonical_path,
            distribution=result.distribution,
            minecraft_version=result.minecraft_version,
            loader_version=None,
            is_fixture=result.is_fixture,
        )
        db.add(profile)
        db.flush()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="profile_import",
                result="success",
                safe_detail=f"Recorded read-only import for {result.distribution} profile",
            )
        )
        db.commit()
        return {
            "id": profile.id,
            "name": profile.name,
            "distribution": profile.distribution,
            "minecraft_version": profile.minecraft_version,
            "is_fixture": profile.is_fixture,
        }

    @app.get("/api/v1/provision/versions/{distribution}")
    async def provision_versions(distribution: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        try:
            versions = await list_versions(http_client, distribution)
        except ProvisionError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"distribution": distribution, "versions": versions}

    @app.post("/api/v1/provision", status_code=201)
    async def provision(payload: ProvisionRequest, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        java_executable: str | None = None
        if payload.distribution in {"forge", "quilt", "neoforge"}:
            runtime = find_java(
                required_java_major(payload.minecraft_version), discover_java_runtimes()
            )
            if runtime is None:
                raise HTTPException(
                    409,
                    "That loader uses an official Java installer, but no compatible Java "
                    "runtime was found on this computer.",
                )
            java_executable = runtime.path
        try:
            result = await provision_profile(
                http_client,
                config.server_root,
                payload.directory_name,
                payload.distribution,
                payload.minecraft_version,
                payload.loader_version,
                java_executable,
            )
        except ProvisionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "The new server folder could not be created.") from exc
        profile = Profile(
            name=payload.name.strip(),
            server_directory=result.directory,
            distribution=payload.distribution,
            minecraft_version=payload.minecraft_version,
            loader_version=result.plan.loader_version,
            is_fixture=False,
        )
        db.add(profile)
        db.flush()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="profile_provision",
                result="success",
                safe_detail=(
                    f"Downloaded {payload.distribution} {payload.minecraft_version} "
                    f"(sha256 {result.sha256})"
                ),
            )
        )
        db.commit()
        return {
            "id": profile.id,
            "name": profile.name,
            "distribution": profile.distribution,
            "minecraft_version": profile.minecraft_version,
            "loader_version": profile.loader_version,
            "directory": result.directory,
            "sha256": result.sha256,
            "notes": result.plan.notes,
            "eula_accepted": False,
        }

    @app.post("/api/v1/profiles/{profile_id}/eula")
    def accept_eula(
        profile_id: str, payload: EulaRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        if not payload.accept:
            raise HTTPException(422, "The EULA can only be recorded as explicitly accepted.")
        directory = profile_directory(profile_id, db)
        eula_path = directory / "eula.txt"
        staging = directory / ".eula.txt.tmp"
        try:
            staging.write_text(
                "# Accepted through the Blockstead dashboard.\n"
                "# By changing this you agree to the Minecraft EULA "
                "(https://aka.ms/MinecraftEULA).\neula=true\n",
                encoding="utf-8",
            )
            staging.replace(eula_path)
        except OSError as exc:
            raise HTTPException(
                409, "Blockstead could not write eula.txt in the profile folder."
            ) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="eula_accept",
                result="success",
                safe_detail=f"Recorded EULA acceptance for profile {profile_id}",
            )
        )
        db.commit()
        return {"profile_id": profile_id, "eula_accepted": True}

    @app.put("/api/v1/profiles/{profile_id}/minecraft-version")
    def set_minecraft_version(
        profile_id: str, payload: MinecraftVersionRequest, request: Request, db: Db
    ) -> dict[str, object]:
        # Detection covers folders that identify themselves. This is the answer
        # for the ones that do not, so an owner is never stuck with a server
        # Blockstead refuses to act on.
        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        previous = profile.minecraft_version
        profile.minecraft_version = payload.minecraft_version
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="profile_version",
                result="success",
                safe_detail=(
                    f"Recorded Minecraft version {payload.minecraft_version} "
                    f"(was {previous or 'unknown'})"
                ),
            )
        )
        db.commit()
        return {
            "id": profile.id,
            "name": profile.name,
            "distribution": profile.distribution,
            "minecraft_version": profile.minecraft_version,
        }

    def profile_directory(profile_id: str, db: Session) -> Path:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        try:
            directory = canonical_child(Path(profile.server_directory), config.server_root)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409,
                (
                    "This profile does not point to an individual server folder inside the "
                    "allowed server root. Remove the profile record without deleting files, "
                    "then import the individual server folder."
                ),
            ) from exc
        conflicts = overlapping_profiles(directory, db, exclude_profile_id=profile.id)
        if any(directory == other or directory in other.parents for _, other in conflicts):
            raise HTTPException(
                409,
                (
                    "This profile folder contains or duplicates another managed server folder. "
                    "Remove the overlapping profile record without deleting files before "
                    "continuing."
                ),
            )
        return directory

    async def build_loader_migration_review(
        profile: Profile, target_distribution: str, db: Session
    ) -> dict[str, object]:
        source = profile_directory(profile.id, db)
        refresh_profile_facts([profile], db)
        if profile.distribution not in DISTRIBUTIONS or profile.distribution == "unknown":
            raise HTTPException(409, "Blockstead does not recognize this server's current loader.")
        if not profile.minecraft_version:
            raise HTTPException(
                409, "Blockstead could not determine this server's Minecraft version."
            )
        try:
            provision_plan = await resolve_plan(
                http_client, target_distribution, profile.minecraft_version, None
            )
        except ProvisionError as exc:
            raise HTTPException(400, str(exc)) from exc

        properties = read_properties(source)
        level_name, roots = discover_world_roots(
            source, safe_level_name(properties.get("level-name"))
        )
        view = read_extensions(source, profile.distribution)
        extensions = classify_extensions(view.entries, profile.distribution, target_distribution)
        required_java = required_java_major(profile.minecraft_version)
        runtime = (
            find_java(required_java, discover_java_runtimes())
            if required_java is not None
            else None
        )

        newest_backup = db.scalar(
            select(BackupRecord)
            .where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "completed",
            )
            .order_by(BackupRecord.created_at.desc())
            .limit(1)
        )
        backup_id: str | None = None
        backup_detail = "Create a verified backup before migrating this world."
        backup_age_hours: float | None = None
        backup_verified = False
        if newest_backup is not None and newest_backup.file_name and newest_backup.manifest_name:
            try:
                await asyncio.to_thread(
                    verify_backup_archive,
                    config.data_dir,
                    profile.id,
                    newest_backup.file_name,
                    newest_backup.manifest_name,
                    newest_backup.sha256,
                )
                created = newest_backup.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)  # noqa: UP017
                backup_age_hours = max(
                    0.0,
                    (datetime.now(timezone.utc) - created).total_seconds() / 3600,  # noqa: UP017
                )
                backup_verified = backup_age_hours <= FRESH_PROTECTION_HOURS
                backup_id = newest_backup.id
                backup_detail = (
                    f"Verified backup {newest_backup.id} is {backup_age_hours:.1f} hours old."
                    if backup_verified
                    else "The newest verified backup is older than 24 hours."
                )
            except RestoreError as exc:
                backup_detail = str(exc)

        measured_roots = [tree_size(root.source) for root in roots]
        measured_world = (
            sum(size for size in measured_roots if size is not None)
            if roots and all(size is not None for size in measured_roots)
            else None
        )
        disk_free = int(psutil.disk_usage(str(config.server_root)).free)
        required_space = (
            measured_world + BACKUP_OVERHEAD_BYTES if measured_world is not None else None
        )
        stopped = manager.state.value in {"STOPPED", "CRASHED"}
        blockers: list[str] = []
        if not stopped:
            blockers.append("Stop the active Minecraft server before creating a modded copy.")
        if not roots:
            blockers.append("No supported world folders were found to copy.")
        if not backup_verified:
            blockers.append("Create a fresh verified backup before migrating.")
        if required_java is not None and runtime is None:
            blockers.append(
                f"Install Java {required_java} before creating this {target_distribution} server."
            )
        if required_space is None:
            blockers.append("Blockstead could not measure the world safely.")
        elif disk_free < required_space:
            blockers.append("The server disk does not have enough free space for a safe copy.")

        review_id = review_fingerprint(
            profile_id=profile.id,
            source_distribution=profile.distribution,
            minecraft_version=profile.minecraft_version,
            target_distribution=target_distribution,
            loader_version=provision_plan.loader_version,
            level_name=level_name,
            roots=roots,
            entries=view.entries,
            backup_id=backup_id,
        )
        return {
            "review_id": review_id,
            "profile_id": profile.id,
            "source_distribution": profile.distribution,
            "target_distribution": target_distribution,
            "minecraft_version": profile.minecraft_version,
            "loader_version": provision_plan.loader_version,
            "level_name": level_name,
            "worlds": [root.name for root in roots],
            "world_size_bytes": measured_world,
            "disk_free_bytes": disk_free,
            "required_java_major": required_java,
            "java_ready": required_java is None or runtime is not None,
            "stopped": stopped,
            "protection": {
                "verified": backup_verified,
                "backup_id": backup_id,
                "age_hours": backup_age_hours,
                "detail": backup_detail,
            },
            "extensions": [entry.model_dump() for entry in extensions],
            "modded_world_warning": bool(view.entries) or profile.distribution != "vanilla",
            "blockers": blockers,
            "ready": not blockers,
        }

    @app.post("/api/v1/profiles/{profile_id}/loader-migration/review")
    async def loader_migration_review(
        profile_id: str,
        payload: MigrationReviewRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        return await build_loader_migration_review(profile, payload.target_distribution, db)

    @app.post("/api/v1/profiles/{profile_id}/loader-migration/apply", status_code=201)
    async def loader_migration_apply(
        profile_id: str,
        payload: MigrationApplyRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        fresh = await build_loader_migration_review(profile, payload.target_distribution, db)
        if fresh["review_id"] != payload.review_id:
            raise HTTPException(
                409, "This server changed after the migration review. Review it again."
            )
        blockers = cast(list[str], fresh["blockers"])
        if blockers:
            raise HTTPException(409, blockers[0])
        protection = cast(dict[str, object], fresh["protection"])
        if protection.get("backup_id") != payload.backup_id:
            raise HTTPException(409, "Choose the fresh verified backup from this review.")
        if fresh["modded_world_warning"] and not payload.acknowledge_modded_world:
            raise HTTPException(
                422,
                "Acknowledge that unavailable source mods may leave custom world content "
                "unreadable in the new loader.",
            )
        if payload.loader_version != fresh["loader_version"]:
            raise HTTPException(
                409, "The recommended loader version changed. Review the migration again."
            )

        required_java = cast(int | None, fresh["required_java_major"])
        runtime = (
            find_java(required_java, discover_java_runtimes())
            if required_java is not None
            else None
        )
        java_executable = (
            runtime.path
            if runtime is not None and payload.target_distribution in {"forge", "quilt", "neoforge"}
            else None
        )
        try:
            provisioned = await provision_profile(
                http_client,
                config.server_root,
                payload.directory_name,
                payload.target_distribution,
                cast(str, fresh["minecraft_version"]),
                payload.loader_version,
                java_executable,
            )
        except ProvisionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "The new server folder could not be created.") from exc

        target = Path(provisioned.directory)
        source = profile_directory(profile.id, db)
        roots = migration_world_roots(source, cast(str, fresh["level_name"]))
        try:
            copied = await asyncio.to_thread(
                copy_worlds,
                roots,
                target,
                cast(str, fresh["level_name"]),
                profile.distribution,
                payload.target_distribution,
            )
        except (OSError, ValueError) as exc:
            await asyncio.to_thread(shutil.rmtree, target, True)
            raise HTTPException(
                409,
                "The world copy did not complete. The incomplete target was removed and "
                "the source was not changed.",
            ) from exc

        created = Profile(
            name=payload.name.strip(),
            server_directory=provisioned.directory,
            distribution=payload.target_distribution,
            minecraft_version=cast(str, fresh["minecraft_version"]),
            loader_version=provisioned.plan.loader_version,
            is_fixture=False,
        )
        db.add(created)
        db.flush()
        db.add_all(
            [
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="loader_migration",
                    result="source_retained",
                    safe_detail=(
                        f"Created protected {payload.target_distribution} copy "
                        f"{created.name}; source profile retained"
                    ),
                ),
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=created.id,
                    category="loader_migration",
                    result="success",
                    safe_detail=(
                        f"Copied {', '.join(copied)} from {profile.name} using verified "
                        f"backup {payload.backup_id}"
                    ),
                ),
            ]
        )
        db.commit()
        return {
            "id": created.id,
            "name": created.name,
            "distribution": created.distribution,
            "minecraft_version": created.minecraft_version,
            "loader_version": created.loader_version,
            "worlds_copied": copied,
            "source_profile_id": profile.id,
            "source_unchanged": True,
            "extensions": fresh["extensions"],
            "next_route": f"/servers/{created.id}/mods?migration=1",
            "eula_accepted": False,
        }

    @app.get("/api/v1/profiles/{profile_id}/settings")
    def profile_settings(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return read_settings(profile_directory(profile_id, db)).model_dump()

    @app.post("/api/v1/profiles/{profile_id}/settings/preview")
    def preview_profile_settings(
        profile_id: str, payload: SettingsUpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        mutation(request, db)
        requested = {change.key: change.value for change in payload.changes}
        try:
            preview = preview_settings_update(
                profile_directory(profile_id, db), payload.revision, requested
            )
        except SettingsConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SettingsValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return preview.model_dump()

    @app.put("/api/v1/profiles/{profile_id}/settings")
    def update_profile_settings(
        profile_id: str, payload: SettingsUpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        requested = {change.key: change.value for change in payload.changes}
        try:
            result = apply_settings_update(
                profile_directory(profile_id, db),
                config.data_dir,
                profile_id,
                payload.revision,
                requested,
            )
        except SettingsConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SettingsValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                409,
                "Blockstead could not snapshot and safely replace server.properties.",
            ) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="settings_update",
                result="success",
                safe_detail=(
                    f"Updated {len(result.changes)} settings for profile {profile_id}; "
                    f"recovery snapshot {result.snapshot_name}"
                ),
            )
        )
        db.commit()
        return result.model_dump()

    @app.get("/api/v1/profiles/{profile_id}/settings/raw")
    def profile_settings_raw(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return read_raw_settings(profile_directory(profile_id, db)).model_dump()

    @app.post("/api/v1/profiles/{profile_id}/settings/raw/preview")
    def preview_profile_settings_raw(
        profile_id: str, payload: RawSettingsUpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        mutation(request, db)
        try:
            preview = preview_raw_settings(
                profile_directory(profile_id, db), payload.revision, payload.content
            )
        except SettingsConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SettingsValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        return preview.model_dump()

    @app.put("/api/v1/profiles/{profile_id}/settings/raw")
    def update_profile_settings_raw(
        profile_id: str, payload: RawSettingsUpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        try:
            result = apply_raw_settings(
                profile_directory(profile_id, db),
                config.data_dir,
                profile_id,
                payload.revision,
                payload.content,
            )
        except SettingsConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SettingsValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                409,
                "Blockstead could not snapshot and safely replace server.properties.",
            ) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="settings_raw_update",
                result="success",
                safe_detail=(
                    f"Replaced server.properties for profile {profile_id} through the "
                    f"advanced editor; recovery snapshot {result.snapshot_name}"
                ),
            )
        )
        db.commit()
        return result.model_dump()

    @app.get("/api/v1/profiles/{profile_id}/players")
    def profile_players(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return read_players(profile_directory(profile_id, db)).model_dump()

    @app.get("/api/v1/profiles/{profile_id}/players/roster")
    async def profile_players_roster(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        directory = profile_directory(profile_id, db)
        players = read_players(directory)
        status = None
        snapshot = manager.snapshot()
        if app.state.active_profile_id == profile_id and snapshot["state"] == "RUNNING":
            status = await minecraft_status(read_properties(directory))
        names = roster_names(players, status)
        sessions = summarize_sessions(
            db,
            profile_id,
            names,
            datetime.now(timezone.utc),  # noqa: UP017
        )
        return build_roster(players, status, sessions).model_dump()

    @app.get("/api/v1/profiles/{profile_id}/extensions")
    def profile_extensions(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is not None:
            cleanup_expired(directory / info.extension_directory)
        return read_extensions(directory, profile.distribution).model_dump()

    @app.get("/api/v1/profiles/{profile_id}/shared-map")
    async def profile_shared_map(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        view = read_shared_map(directory, profile.distribution)
        snapshot = manager.snapshot()
        running = (
            app.state.active_profile_id == profile.id and snapshot["state"] == "RUNNING"
        )
        if not running:
            health = {
                "state": "not_running",
                "detail": "Start this server before checking its map web service.",
                "checked_at": None,
            }
        else:
            url, unavailable = local_health_url(view)
            if url is None:
                health = {
                    "state": "unavailable",
                    "detail": unavailable or "Map health is unavailable.",
                    "checked_at": datetime.now(UTC).isoformat(),
                }
            else:
                try:
                    response = await http_client.get(
                        url,
                        headers={"Range": "bytes=0-1024"},
                        timeout=httpx.Timeout(2.0),
                        follow_redirects=False,
                    )
                    health = {
                        "state": "available" if response.status_code < 500 else "unhealthy",
                        "detail": (
                            "The local squaremap web service responded with HTTP "
                            f"{response.status_code}."
                        ),
                        "checked_at": datetime.now(UTC).isoformat(),
                    }
                except httpx.HTTPError:
                    health = {
                        "state": "unreachable",
                        "detail": (
                            "The local squaremap web service did not respond on its "
                            "configured port."
                        ),
                        "checked_at": datetime.now(UTC).isoformat(),
                    }
        return {**view.model_dump(), "health": health}

    @app.post("/api/v1/profiles/{profile_id}/shared-map/low-resource")
    async def apply_shared_map_low_resource_profile(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        snapshot = manager.snapshot()
        if app.state.active_profile_id == profile.id and snapshot["state"] not in {
            "STOPPED",
            "CRASHED",
        }:
            raise HTTPException(
                409, "Stop this server before changing squaremap's render profile."
            )
        try:
            result = await asyncio.to_thread(
                apply_low_resource_profile,
                profile_directory(profile_id, db),
                profile.distribution,
            )
        except SharedMapError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="shared_map_profile",
                result="success",
                safe_detail=(
                    "Applied squaremap's low-resource profile; both render pools are capped at "
                    f"one thread, with backup {result.backup_path}"
                ),
            )
        )
        db.commit()
        return {
            **result.model_dump(),
            "detail": (
                "Capped squaremap's normal and background render pools at one thread. "
                "The previous config was kept in Blockstead's server configuration backups."
            ),
        }

    def extension_context(profile_id: str, db: Session) -> tuple[Profile, Path]:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            raise HTTPException(409, "This server distribution does not load plugins or mods.")
        return profile, directory / info.extension_directory

    def command_provider_context(
        profile_id: str, db: Session
    ) -> tuple[Profile, ExtensionsView, dict[str, str]]:
        """Load the single evidence set used by command presentation and POST gating."""
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        view = read_extensions(directory, profile.distribution)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            return profile, view, {}
        extension_dir = directory / info.extension_directory
        try:
            origins = load_origin_map(extension_dir)
        except OriginRegistryError:
            origins = {}
        origin_project_ids = {
            file_name: origin.project_id
            for file_name, origin in origins.items()
            if origin.project_id
        }
        return profile, view, origin_project_ids

    def require_published_checksums(planned: list[PlannedFile]) -> None:
        """Catalog installs must have a publisher digest, not merely HTTPS."""
        if not planned:
            raise HTTPException(409, "The catalog did not provide any extension files to install.")
        missing = [
            item.file_name for item in planned if not item.checksum_algorithm or not item.checksum
        ]
        if missing:
            raise HTTPException(
                409,
                "Blockstead will not automatically install files without a published "
                f"checksum: {', '.join(missing)}.",
            )
        invalid = [
            item.file_name
            for item in planned
            if item.checksum_algorithm not in SUPPORTED_CHECKSUMS
            or not isinstance(item.checksum, str)
            or not re.fullmatch(r"[0-9a-fA-F]+", item.checksum)
        ]
        if invalid:
            raise HTTPException(
                409,
                "Blockstead will not automatically install files with an unsupported "
                f"or invalid published checksum: {', '.join(invalid)}.",
            )

    async def stage_extension_install(
        extension_dir: Path,
        planned: list[PlannedFile],
        *,
        retire_names: frozenset[str] = frozenset(),
        expected_retired_checksums: dict[str, tuple[str, str]] | None = None,
    ) -> tuple[list[dict[str, object]], list[str]]:
        """Download a catalog plan outside the live loadout, then promote it safely."""
        require_published_checksums(planned)
        names = [item.file_name for item in planned]
        if len(names) != len(set(names)):
            raise HTTPException(409, "The catalog returned duplicate extension file names.")
        staging: Path | None = None
        staged: list[tuple[PlannedFile, str]] = []
        skipped: list[str] = []
        try:
            directory = ensure_managed_directory(extension_dir, create=True)
            disabled = ensure_managed_directory(disabled_directory(directory))
            staging = create_staging_directory(directory)
            for planned_file in planned:
                target = directory / planned_file.file_name
                disabled_target = disabled / planned_file.file_name
                if disabled_target.exists() or disabled_target.is_symlink():
                    raise HTTPException(
                        409,
                        f"A disabled extension already uses the name {planned_file.file_name}. "
                        "Enable or remove it before installing another file with that name.",
                    )
                if target.exists() or target.is_symlink():
                    if planned_file.file_name not in retire_names:
                        assert planned_file.checksum_algorithm is not None
                        assert planned_file.checksum is not None
                        if checksum_matches(
                            target, planned_file.checksum_algorithm, planned_file.checksum
                        ):
                            skipped.append(planned_file.file_name)
                            continue
                        raise HTTPException(
                            409,
                            f"A file named {planned_file.file_name} already exists with a "
                            "different checksum. Nothing was replaced.",
                        )
                try:
                    sha256 = await download_verified_file(
                        http_client,
                        planned_file.url,
                        staging,
                        planned_file.file_name,
                        planned_file.checksum_algorithm,
                        planned_file.checksum,
                    )
                except ProvisionError as exc:
                    raise HTTPException(400, str(exc)) from exc
                staged.append((planned_file, sha256))

            if staged:
                promote_staged_files(
                    directory,
                    staging,
                    [item.file_name for item, _ in staged],
                    retire_names=retire_names,
                    expected_retired_checksums=expected_retired_checksums,
                )
        except ExtensionOpsError as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
        return (
            [
                {
                    "file_name": item.file_name,
                    "version_number": item.version_number,
                    "required_by": item.required_by,
                    "sha256": sha256,
                }
                for item, sha256 in staged
            ],
            skipped,
        )

    def persist_reviewed_batch(
        extension_dir: Path,
        file_names: list[str],
        *,
        review_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Retain the exact newly promoted files for one later private test."""

        if not file_names:
            return None, None
        if len(file_names) > 20:
            return None, "This install is too large to quarantine as one reviewed batch."
        identity = review_id or secrets.token_hex(8)
        try:
            entries = [inspect_extension_jar(extension_dir / name) for name in file_names]
            batch = identify_reviewed_batch(extension_dir, identity, entries)
            save_reviewed_batch(extension_dir, batch)
        except SafeStartError as exc:
            return None, str(exc)
        return identity, None

    def missing_paper_dependencies(
        directory: Path, profile: Profile, planned: list[PlannedFile]
    ) -> list[str]:
        """Paper names dependencies, but Hangar cannot safely map them to jars."""
        installed = {
            entry.identifier.casefold()
            for entry in read_extensions(directory, profile.distribution).entries
            if entry.identifier
        }
        required = {
            name
            for item in planned
            for name in item.required_plugins
            if name.casefold() not in installed
        }
        return sorted(required, key=str.casefold)

    def require_server_stopped() -> None:
        if manager.state.value not in {"STOPPED", "CRASHED"}:
            raise HTTPException(409, "Stop the server before changing mods or configuration.")

    def catalog_project_pattern(source: str) -> re.Pattern[str]:
        if source == "hangar":
            return HANGAR_PROJECT_PATTERN
        if source == "curseforge":
            return CURSEFORGE_PROJECT_PATTERN
        if source == "modrinth":
            return PROJECT_ID_PATTERN
        raise HTTPException(422, "That catalog is not one Blockstead knows.")

    CURSEFORGE_KEY_NAME = "curseforge_api_key"

    def curseforge_key(db: Session) -> str | None:
        row = db.get(AppSecret, CURSEFORGE_KEY_NAME)
        return row.value if row else None

    @app.get("/api/v1/settings/curseforge")
    def curseforge_settings(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return {"configured": curseforge_key(db) is not None}

    @app.put("/api/v1/settings/curseforge")
    def curseforge_settings_update(
        payload: CurseForgeKeyRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        row = db.get(AppSecret, CURSEFORGE_KEY_NAME)
        if row is None:
            db.add(AppSecret(key=CURSEFORGE_KEY_NAME, value=payload.api_key))
        else:
            row.value = payload.api_key
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="settings_change",
                result="success",
                safe_detail="Stored a CurseForge API key",
            )
        )
        db.commit()
        return {"configured": True}

    @app.delete("/api/v1/settings/curseforge")
    def curseforge_settings_clear(request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        row = db.get(AppSecret, CURSEFORGE_KEY_NAME)
        if row is not None:
            db.delete(row)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="settings_change",
                result="success",
                safe_detail="Removed the CurseForge API key",
            )
        )
        db.commit()
        return {"configured": False}

    @app.get("/api/v1/profiles/{profile_id}/catalog/search")
    async def extension_search(
        profile_id: str,
        query: str,
        request: Request,
        db: Db,
        source: str = "modrinth",
        categories: str = "",
        sort: str = "relevance",
        offset: int = 0,
    ) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        catalog_project_pattern(source)
        if not query.strip() or len(query) > 100:
            raise HTTPException(422, "Enter a search of at most 100 characters.")
        if len(categories) > 300:
            raise HTTPException(422, "That category filter is too long.")
        chosen_categories = [item for item in categories.split(",") if item]
        try:
            if source == "curseforge":
                page = await curseforge_search(
                    http_client,
                    curseforge_key(db),
                    profile.distribution,
                    profile.minecraft_version,
                    query.strip(),
                    categories=chosen_categories,
                    sort=sort,
                    offset=max(0, offset),
                )
            else:
                search_catalog = hangar_search if source == "hangar" else modrinth_search
                page = await search_catalog(
                    http_client,
                    profile.distribution,
                    profile.minecraft_version,
                    query.strip(),
                    categories=chosen_categories,
                    sort=sort,
                    offset=max(0, offset),
                )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "minecraft_version": profile.minecraft_version,
            "source": source,
            "projects": [project.model_dump() for project in page.projects],
            "total": page.total,
            "offset": page.offset,
            "limit": page.limit,
        }

    @app.get("/api/v1/profiles/{profile_id}/catalog/categories")
    async def extension_categories(
        profile_id: str, request: Request, db: Db, source: str = "modrinth"
    ) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        catalog_project_pattern(source)
        try:
            if source == "curseforge":
                names = await curseforge_categories(
                    http_client, curseforge_key(db), profile.distribution
                )
            else:
                list_catalog_categories = (
                    hangar_categories if source == "hangar" else modrinth_categories
                )
                names = await list_catalog_categories(http_client, profile.distribution)
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"source": source, "categories": names}

    async def recommendation_status(
        profile: Profile,
        recommendation: ExtensionRecommendation,
        active: set[str],
        states: dict[str, tuple[bool, bool]],
    ) -> dict[str, object]:
        active_state, disabled_state = states[recommendation.id]
        missing_dependencies = [
            dependency for dependency in recommendation.dependencies if dependency not in active
        ]
        version: object | None = None
        availability = "unknown"
        detail = "Compatibility could not be checked right now."

        if recommendation.runtime_mode == "paper-capability":
            availability = "bundled" if active_state else "unavailable"
            detail = (
                "Paper supplies the spark command family for this profile."
                if active_state
                else "This server distribution does not provide the bundled capability."
            )
        else:
            try:
                if recommendation.source == "hangar":
                    versions = await hangar_versions(
                        http_client,
                        profile.distribution,
                        profile.minecraft_version,
                        recommendation.project_id,
                    )
                else:
                    versions = await modrinth_versions(
                        http_client,
                        profile.distribution,
                        profile.minecraft_version,
                        recommendation.project_id,
                    )
                chosen = next(
                    (item for item in versions if item.version_type == "release"),
                    versions[0] if versions else None,
                )
                if chosen is not None:
                    version = chosen.model_dump()
                    availability = "available"
                    detail = "A compatible release is available from the curated catalog."
                else:
                    availability = "unavailable"
                    detail = "No compatible release is listed for this server."
            except CatalogError:
                # Keep the curated recommendation visible when the catalog is
                # unavailable; the owner can still open its project page.
                availability = "unknown"
                detail = "Could not check compatible releases right now."

        if availability == "bundled" and active_state:
            state = "bundled"
        elif active_state and not missing_dependencies:
            state = "active"
        elif disabled_state:
            state = "disabled"
        elif missing_dependencies:
            state = "needs-dependency"
        else:
            state = availability
        return {
            "id": recommendation.id,
            "project_id": recommendation.project_id,
            "source": recommendation.source,
            "title": recommendation.title,
            "purpose": recommendation.purpose,
            "state": state,
            "availability": availability,
            "detail": detail,
            "active": active_state and not missing_dependencies,
            "installed": active_state or disabled_state,
            "disabled": disabled_state,
            "dependencies": list(recommendation.dependencies),
            "missing_dependencies": missing_dependencies,
            "conflict_group": recommendation.conflict_group,
            "command_pack_id": recommendation.command_pack_id,
            "latest_version": version,
            "project_url": (
                f"https://hangar.papermc.io/{recommendation.project_id}"
                if recommendation.source == "hangar"
                else (
                    "https://modrinth.com/"
                    f"{'plugin' if profile.distribution == 'paper' else 'mod'}/"
                    f"{recommendation.project_id}"
                )
            ),
        }

    @app.get("/api/v1/profiles/{profile_id}/extensions/recommendations")
    async def extension_recommendations(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            return {
                "distribution": profile.distribution,
                "minecraft_version": profile.minecraft_version,
                "recommendations": [],
            }
        profile, view, origin_project_ids = command_provider_context(profile_id, db)
        candidates, active, states = recommendation_payload(
            profile.distribution,
            view.entries,
            view.disabled_entries,
            profile.minecraft_version,
            origin_project_ids,
        )
        catalog_limit = asyncio.Semaphore(4)

        async def bounded_status(item: ExtensionRecommendation) -> dict[str, object]:
            async with catalog_limit:
                return await recommendation_status(profile, item, active, states)

        statuses = await asyncio.gather(*(bounded_status(item) for item in candidates))
        return {
            "distribution": profile.distribution,
            "minecraft_version": profile.minecraft_version,
            "recommendations": list(statuses),
        }

    @app.get("/api/v1/profiles/{profile_id}/catalog/versions")
    async def extension_versions(
        profile_id: str, project_id: str, request: Request, db: Db, source: str = "modrinth"
    ) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        if not catalog_project_pattern(source).match(project_id):
            raise HTTPException(422, "That project id is not one Blockstead accepts.")
        try:
            if source == "curseforge":
                versions = await curseforge_versions(
                    http_client,
                    curseforge_key(db),
                    profile.distribution,
                    profile.minecraft_version,
                    project_id,
                )
            else:
                list_catalog_versions = hangar_versions if source == "hangar" else modrinth_versions
                versions = await list_catalog_versions(
                    http_client, profile.distribution, profile.minecraft_version, project_id
                )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"source": source, "versions": [version.model_dump() for version in versions]}

    @app.post("/api/v1/profiles/{profile_id}/extensions/install", status_code=201)
    async def extension_install(
        profile_id: str, payload: InstallRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        if not catalog_project_pattern(payload.source).match(payload.project_id):
            raise HTTPException(422, "That project id is not one Blockstead accepts.")
        try:
            if payload.source == "curseforge":
                planned = await curseforge_plan_install(
                    http_client,
                    curseforge_key(db),
                    profile.distribution,
                    profile.minecraft_version,
                    payload.project_id,
                    payload.version_id,
                )
            else:
                plan_catalog_install = (
                    hangar_plan_install if payload.source == "hangar" else plan_install
                )
                planned = await plan_catalog_install(
                    http_client,
                    profile.distribution,
                    profile.minecraft_version,
                    payload.project_id,
                    payload.version_id,
                )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        if payload.source == "hangar":
            missing = missing_paper_dependencies(extension_dir.parent, profile, planned)
            if missing:
                raise HTTPException(
                    409,
                    "This Paper plugin requires installed plugins that Blockstead cannot "
                    f"safely resolve from Hangar: {', '.join(missing)}.",
                )
        installed, skipped = await stage_extension_install(extension_dir, planned)
        batch_id, batch_warning = persist_reviewed_batch(
            extension_dir, [str(item["file_name"]) for item in installed]
        )
        origin_warning: str | None = None
        try:
            record_catalog_files(extension_dir, payload.source, planned)
        except OriginRegistryError as exc:
            origin_warning = str(exc)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_install",
                result="success",
                safe_detail=(
                    f"Installed {len(installed)} file(s) from "
                    f"{payload.source} project {payload.project_id}"
                ),
            )
        )
        db.commit()
        return {
            "installed": installed,
            "skipped": skipped,
            "restart_required": True,
            "batch_id": batch_id,
            "warnings": [
                warning for warning in (origin_warning, batch_warning) if warning is not None
            ],
        }

    @app.post("/api/v1/profiles/{profile_id}/extensions/toggle")
    def extension_toggle(
        profile_id: str, payload: ToggleRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        _, extension_dir = extension_context(profile_id, db)
        try:
            set_enabled(extension_dir, payload.file_name, payload.enabled)
        except ExtensionOpsError as exc:
            raise HTTPException(409, str(exc)) from exc
        state = "enabled" if payload.enabled else "disabled"
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_toggle",
                result="success",
                safe_detail=f"Marked {payload.file_name} as {state}",
            )
        )
        db.commit()
        return {
            "file_name": payload.file_name,
            "enabled": payload.enabled,
            "restart_required": True,
        }

    @app.get("/api/v1/profiles/{profile_id}/extensions/updates")
    async def extension_updates(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        view = read_extensions(profile_directory(profile_id, db), profile.distribution)
        entries = [entry for entry in view.entries if entry.sha512]
        try:
            found = await modrinth_check_updates(
                http_client,
                profile.distribution,
                profile.minecraft_version,
                [entry.sha512 for entry in entries if entry.sha512],
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        updates: list[dict[str, object]] = []
        unknown: list[str] = []
        up_to_date = 0
        for entry in entries:
            if entry.sha512 not in found:
                unknown.append(entry.file_name)
                continue
            planned = found[entry.sha512]
            if planned is None:
                up_to_date += 1
                continue
            updates.append(
                {
                    "file_name": entry.file_name,
                    "installed_version": entry.version,
                    "new_version_number": planned.version_number,
                    "new_file_name": planned.file_name,
                    "project_id": planned.project_id,
                    "version_id": planned.version_id,
                }
            )
        return {
            "updates": updates,
            "up_to_date": up_to_date,
            "unknown": sorted(unknown),
            "checked": len(entries),
        }

    async def reviewed_extension_update(
        profile: Profile,
        extension_dir: Path,
        entry: ExtensionEntry,
    ) -> tuple[list[PlannedFile], ExtensionUpdateReview]:
        """Re-resolve one exact update and its dependency closure."""

        assert entry.sha512 is not None
        try:
            found = await modrinth_check_updates(
                http_client,
                profile.distribution,
                profile.minecraft_version,
                [entry.sha512],
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        planned_update = found.get(entry.sha512)
        if planned_update is None:
            raise HTTPException(409, "No newer compatible version is known for that file.")
        try:
            update_plan = await plan_install(
                http_client,
                profile.distribution,
                profile.minecraft_version,
                planned_update.project_id,
                planned_update.version_id,
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        if (
            not update_plan
            or update_plan[0].project_id != planned_update.project_id
            or update_plan[0].version_id != planned_update.version_id
            or update_plan[0].file_name != planned_update.file_name
            or update_plan[0].checksum_algorithm != planned_update.checksum_algorithm
            or update_plan[0].checksum != planned_update.checksum
        ):
            raise HTTPException(409, "Modrinth returned an unusable extension update plan.")
        directory = ensure_managed_directory(extension_dir, create=True)
        verified_existing: set[str] = set()
        for item in update_plan[1:]:
            target = directory / item.file_name
            if (
                target.is_file()
                and not target.is_symlink()
                and item.checksum_algorithm
                and item.checksum
                and checksum_matches(target, item.checksum_algorithm, item.checksum)
            ):
                verified_existing.add(item.file_name)
        try:
            review = build_extension_update_review(
                profile_id=profile.id,
                distribution=profile.distribution,
                minecraft_version=profile.minecraft_version,
                required_java=required_java_major(profile.minecraft_version),
                installed_name=entry.file_name,
                installed_version=entry.version,
                installed_sha512=entry.sha512,
                planned=update_plan,
                existing_names=frozenset(verified_existing),
            )
        except ExtensionRecoveryError as exc:
            raise HTTPException(409, str(exc)) from exc
        return update_plan, review

    def extension_update_entry(
        profile_id: str, file_name: str, db: Session
    ) -> tuple[Profile, Path, ExtensionEntry]:
        profile, extension_dir = extension_context(profile_id, db)
        view = read_extensions(profile_directory(profile_id, db), profile.distribution)
        entry = next((item for item in view.entries if item.file_name == file_name), None)
        if entry is None or not entry.sha512:
            raise HTTPException(404, "That file is not in the live extensions folder.")
        return profile, extension_dir, entry

    @app.post("/api/v1/profiles/{profile_id}/extensions/update-review")
    async def extension_update_review(
        profile_id: str,
        payload: UpdateReviewRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Review exact files, dependencies, restart impact, and recovery first."""

        admin = mutation(request, db)
        profile, extension_dir, entry = extension_update_entry(profile_id, payload.file_name, db)
        _, review = await reviewed_extension_update(profile, extension_dir, entry)
        maintenance_plan = await build_maintenance_plan(
            profile, MaintenanceRequest(change_id="extension_update"), db
        )
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="maintenance_preflight",
                result="reviewed",
                safe_detail=(
                    f"Reviewed extension update {entry.file_name} -> "
                    f"{review.new_file_name}; update {review.review_id}; "
                    f"plan {maintenance_plan.plan_id}"
                ),
            )
        )
        db.commit()
        return {
            "review": review.model_dump(),
            "maintenance_plan": maintenance_plan.model_dump(),
        }

    @app.post("/api/v1/profiles/{profile_id}/extensions/update")
    async def extension_apply_update(
        profile_id: str, payload: UpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir, entry = extension_update_entry(profile_id, payload.file_name, db)
        update_plan, review = await reviewed_extension_update(profile, extension_dir, entry)
        if review.review_id != payload.review_id:
            raise HTTPException(
                409,
                "This extension update changed since it was reviewed. Review its files "
                "and dependencies again before applying it.",
            )
        maintenance_plan = await build_maintenance_plan(
            profile, MaintenanceRequest(change_id="extension_update"), db
        )
        if maintenance_plan.plan_id != payload.maintenance_plan_id:
            raise HTTPException(
                409,
                "This server changed since the maintenance review. Run the extension "
                "update review again before applying it.",
            )
        if (
            not maintenance_plan.protection.verified
            or maintenance_plan.protection.age_hours is None
            or maintenance_plan.protection.age_hours > FRESH_PROTECTION_HOURS
        ):
            raise HTTPException(
                409,
                "Create a fresh verified backup, then review this extension update again.",
            )
        planned = update_plan[0]
        if planned.file_name != entry.file_name and (extension_dir / planned.file_name).exists():
            raise HTTPException(409, "A file with the new version's name already exists.")
        assert entry.sha512 is not None
        recovery: Path | None = None
        try:
            previous_origin = load_origin_map(extension_dir).get(entry.file_name)
        except OriginRegistryError:
            previous_origin = None
        try:
            recovery_id, recovery = prepare_extension_recovery(
                recovery_root=config.data_dir,
                profile_id=profile.id,
                extension_directory=extension_dir,
                review=review,
                installed_sha512=entry.sha512,
                old_origin=(previous_origin.model_dump(mode="json") if previous_origin else None),
            )
            changed_names = {
                item.file_name for item in review.files if item.action != "already_present"
            }
            recovery_files: list[tuple[str, str, str]] = []
            for item in update_plan:
                if item.file_name not in changed_names:
                    continue
                if not item.checksum_algorithm or not item.checksum:
                    raise HTTPException(
                        409,
                        "The reviewed update lost a required published checksum.",
                    )
                recovery_files.append((item.file_name, item.checksum_algorithm, item.checksum))
            # Persist the exact recovery contract before live promotion. If the
            # promotion then fails, extension_ops restores the loadout and this
            # private bundle is discarded.
            finalize_extension_recovery(recovery, new_files=recovery_files)
            installed, _ = await stage_extension_install(
                extension_dir,
                update_plan,
                retire_names=frozenset({entry.file_name}),
                expected_retired_checksums={entry.file_name: ("sha512", entry.sha512)},
            )
        except (ExtensionRecoveryError, ExtensionOpsError) as exc:
            if recovery is not None:
                discard_extension_recovery(recovery)
            raise HTTPException(409, str(exc)) from exc
        except HTTPException:
            if recovery is not None:
                discard_extension_recovery(recovery)
            raise
        sha256 = next(
            (str(item["sha256"]) for item in installed if item["file_name"] == planned.file_name),
            None,
        )
        if sha256 is None:
            raise HTTPException(409, "The updated extension file was not installed.")
        batch_id, batch_warning = persist_reviewed_batch(
            extension_dir, [str(item["file_name"]) for item in installed]
        )
        origin_warning: str | None = None
        try:
            forget_origin(extension_dir, entry.file_name)
            record_catalog_files(extension_dir, "modrinth", update_plan)
        except OriginRegistryError as exc:
            origin_warning = str(exc)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_update",
                result="success",
                safe_detail=(
                    f"Updated {entry.file_name} to {planned.file_name} "
                    f"(sha256 {sha256}); recovery {recovery_id}"
                ),
            )
        )
        db.commit()
        return {
            "file_name": planned.file_name,
            "replaced": entry.file_name,
            "version_number": planned.version_number,
            "dependencies_installed": [
                item["file_name"] for item in installed if item["file_name"] != planned.file_name
            ],
            "recovery_id": recovery_id,
            "rollback_detail": review.rollback_detail,
            "restart_required": True,
            "batch_id": batch_id,
            "warnings": [
                warning for warning in (origin_warning, batch_warning) if warning is not None
            ],
        }

    @app.post("/api/v1/profiles/{profile_id}/extensions/update-recovery/{recovery_id}")
    def extension_update_rollback(
        profile_id: str,
        recovery_id: str,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        try:
            recovery = rollback_extension_update(
                recovery_root=config.data_dir,
                profile_id=profile.id,
                recovery_id=recovery_id,
                extension_directory=extension_dir,
            )
        except (ExtensionRecoveryError, ExtensionOpsError) as exc:
            raise HTTPException(409, str(exc)) from exc
        old_name = str(recovery["old_file"])
        origin_warning: str | None = None
        try:
            raw_new_files = recovery.get("new_files")
            if isinstance(raw_new_files, list):
                for item in raw_new_files:
                    if isinstance(item, dict) and isinstance(item.get("file_name"), str):
                        forget_origin(extension_dir, item["file_name"])
            old_origin = recovery.get("old_origin")
            if isinstance(old_origin, dict):
                record_existing_origin(extension_dir, old_name, old_origin)
        except OriginRegistryError as exc:
            origin_warning = str(exc)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="extension_update",
                result="recovered",
                safe_detail=(
                    f"Restored {old_name} from extension recovery {recovery_id}; "
                    "world data was not changed"
                ),
            )
        )
        db.commit()
        return {
            "restored": old_name,
            "restart_required": True,
            "detail": (
                f"Restored {old_name}. Restart the server to load the recovered extension. "
                "World data was not rolled back."
            ),
            "warnings": [origin_warning] if origin_warning else [],
        }

    @app.post("/api/v1/profiles/{profile_id}/extensions/toggle-all")
    def extension_toggle_all(
        profile_id: str, payload: ToggleAllRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        _, extension_dir = extension_context(profile_id, db)
        moved, skipped = set_all_enabled(extension_dir, payload.enabled)
        state = "enabled" if payload.enabled else "disabled"
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_toggle",
                result="success",
                safe_detail=f"Marked all extensions as {state} ({len(moved)} file(s) moved)",
            )
        )
        db.commit()
        return {
            "moved": moved,
            "skipped": skipped,
            "enabled": payload.enabled,
            "restart_required": True,
        }

    @app.delete("/api/v1/profiles/{profile_id}/extensions/{file_name}")
    def extension_remove(
        profile_id: str,
        file_name: str,
        request: Request,
        db: Db,
        disabled: bool = False,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        _, extension_dir = extension_context(profile_id, db)
        try:
            remove_extension(extension_dir, file_name, disabled)
        except ExtensionOpsError as exc:
            raise HTTPException(409, str(exc)) from exc
        try:
            forget_origin(extension_dir, file_name)
        except OriginRegistryError:
            pass
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_remove",
                result="success",
                safe_detail=f"Removed {file_name}",
            )
        )
        db.commit()
        return {"file_name": file_name, "removed": True, "restart_required": True}

    @app.post("/api/v1/profiles/{profile_id}/extensions/upload", status_code=201)
    async def extension_upload(
        profile_id: str, file: UploadFile, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        try:
            target = place_upload(extension_dir, file.filename or "", content)
        except ExtensionOpsError as exc:
            raise HTTPException(400, str(exc)) from exc
        origin_warning: str | None = None
        try:
            record_local_files(extension_dir, [target.name])
        except OriginRegistryError as exc:
            origin_warning = str(exc)
        view = read_extensions(profile_directory(profile_id, db), profile.distribution)
        entry = next((item for item in view.entries if item.file_name == target.name), None)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_upload",
                result="success",
                safe_detail=f"Uploaded {target.name} "
                f"(sha256 {entry.sha256 if entry else 'unknown'})",
            )
        )
        db.commit()
        return {
            "entry": entry.model_dump() if entry else None,
            "warnings": [
                *[warning.model_dump() for warning in view.warnings],
                *([{"code": "origin_record", "message": origin_warning}] if origin_warning else []),
            ],
            "restart_required": True,
        }

    @app.post(
        "/api/v1/profiles/{profile_id}/extensions/manual-import/review",
        status_code=201,
    )
    async def manual_import_review(
        profile_id: str,
        files: list[UploadFile],
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        if not files or len(files) > MAX_IMPORT_FILES:
            raise HTTPException(422, f"Choose between 1 and {MAX_IMPORT_FILES} jar files.")
        cleanup_expired(extension_dir)
        review_id = secrets.token_hex(8)
        try:
            staging = create_manual_staging_directory(extension_dir, review_id)
        except ExtensionOpsError as exc:
            raise HTTPException(409, str(exc)) from exc
        total = 0
        staged_entries: list[ExtensionEntry] = []
        try:
            seen: set[str] = set()
            for upload in files:
                name = upload.filename or ""
                if name in seen:
                    raise ExtensionOpsError(f"The selected files contain duplicate name {name}.")
                seen.add(name)
                content = await upload.read(MAX_UPLOAD_BYTES + 1)
                total += len(content)
                if total > MAX_UPLOAD_BYTES * 2:
                    raise ExtensionOpsError(
                        "The selected jar files are too large to review as one batch."
                    )
                path = stage_uploaded_jar(staging, name, content)
                staged_entries.append(inspect_extension_jar(path))

            native = (
                {"paper"}
                if profile.distribution == "paper"
                else {
                    profile.distribution,
                    *(["fabric"] if profile.distribution == "quilt" else []),
                }
            )
            installed_view = read_extensions(
                profile_directory(profile.id, db), profile.distribution
            )
            installed_ids = {
                item.identifier.casefold()
                for item in [*installed_view.entries, *installed_view.disabled_entries]
                if item.identifier
            }
            staged_ids = {item.identifier.casefold() for item in staged_entries if item.identifier}
            wrong_loader = [
                item.file_name
                for item in staged_entries
                if item.loaders and not (set(item.loaders) & native)
            ]
            client_only = [
                item.file_name for item in staged_entries if item.environment == "client"
            ]
            unknown = [
                item.file_name for item in staged_entries if not item.loaders or not item.identifier
            ]
            missing = sorted(
                {
                    dependency
                    for item in staged_entries
                    for dependency in item.dependencies
                    if dependency.casefold() not in installed_ids | staged_ids
                },
                key=str.casefold,
            )
            conflicts = sorted(
                item.file_name
                for item in staged_entries
                if (extension_dir / item.file_name).exists()
                or (disabled_directory(extension_dir) / item.file_name).exists()
            )
            blockers: list[str] = []
            if wrong_loader:
                blockers.append(
                    f"These files target a different loader: {', '.join(wrong_loader)}."
                )
            if client_only:
                blockers.append(f"These files are client-only: {', '.join(client_only)}.")
            if conflicts:
                blockers.append(
                    f"Files with these names are already installed: {', '.join(conflicts)}."
                )
            if missing:
                blockers.append(
                    "Add these required dependencies to this batch or install them from "
                    f"the catalog first: {', '.join(missing)}."
                )
            manifest = {
                "created_at": time.time(),
                "review_id": review_id,
                "profile_id": profile.id,
                "distribution": profile.distribution,
                "destination": extension_dir.name,
                "files": [entry.model_dump() for entry in staged_entries],
                "unknown_files": unknown,
            }
            save_manifest(staging, manifest)
        except (ExtensionOpsError, OSError, ValueError) as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, ExtensionOpsError):
                raise HTTPException(400, str(exc)) from exc
            raise HTTPException(409, "The manual import review could not be prepared.") from exc
        return {
            **manifest,
            "blockers": blockers,
            "missing_dependencies": missing,
            "requires_acknowledgement": bool(unknown),
            "expires_in_seconds": 60 * 60,
        }

    @app.post(
        "/api/v1/profiles/{profile_id}/extensions/manual-import/apply",
        status_code=201,
    )
    def manual_import_apply(
        profile_id: str,
        payload: ManualImportApplyRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        staging = extension_dir / f".blockstead-manual-{payload.review_id}"
        try:
            manifest = load_manifest(staging)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if (
            manifest.get("review_id") != payload.review_id
            or manifest.get("profile_id") != profile.id
            or manifest.get("distribution") != profile.distribution
        ):
            raise HTTPException(409, "That manual import review belongs to another loadout.")
        raw_files = manifest.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise HTTPException(409, "That manual import review contains no files.")
        reviewed = {
            str(item.get("file_name")): item
            for item in raw_files
            if isinstance(item, dict) and isinstance(item.get("file_name"), str)
        }
        entries = [inspect_extension_jar(staging / name) for name in reviewed]
        if len(entries) != len(raw_files) or any(
            entry.sha256 != reviewed[entry.file_name].get("sha256") for entry in entries
        ):
            raise HTTPException(409, "A staged jar changed after review. Choose the files again.")

        native = (
            {"paper"}
            if profile.distribution == "paper"
            else {
                profile.distribution,
                *(["fabric"] if profile.distribution == "quilt" else []),
            }
        )
        installed = read_extensions(profile_directory(profile.id, db), profile.distribution)
        installed_ids = {
            item.identifier.casefold()
            for item in [*installed.entries, *installed.disabled_entries]
            if item.identifier
        }
        staged_ids = {item.identifier.casefold() for item in entries if item.identifier}
        blockers: list[str] = []
        if any(item.loaders and not (set(item.loaders) & native) for item in entries):
            blockers.append("One or more reviewed files target a different loader.")
        if any(item.environment == "client" for item in entries):
            blockers.append("One or more reviewed files are client-only.")
        if any(
            (extension_dir / item.file_name).exists()
            or (disabled_directory(extension_dir) / item.file_name).exists()
            for item in entries
        ):
            blockers.append("A reviewed file name is already installed.")
        missing = {
            dependency
            for item in entries
            for dependency in item.dependencies
            if dependency.casefold() not in installed_ids | staged_ids
        }
        if missing:
            blockers.append(
                "Required dependencies are still missing: "
                + ", ".join(sorted(missing, key=str.casefold))
                + "."
            )
        unknown = [item for item in entries if not item.loaders or not item.identifier]
        if unknown and not payload.acknowledge_unknown:
            raise HTTPException(
                422,
                "Acknowledge that Blockstead could not verify the compatibility or origin "
                "of every selected jar.",
            )
        if blockers:
            raise HTTPException(409, blockers[0])
        try:
            promote_staged_files(extension_dir, staging, [entry.file_name for entry in entries])
        except ExtensionOpsError as exc:
            raise HTTPException(409, str(exc)) from exc
        warnings: list[str] = []
        try:
            record_local_files(extension_dir, [entry.file_name for entry in entries])
        except OriginRegistryError as exc:
            warnings.append(str(exc))
        batch_id, batch_warning = persist_reviewed_batch(
            extension_dir,
            [entry.file_name for entry in entries],
            review_id=payload.review_id,
        )
        if batch_warning:
            warnings.append(
                "The files were installed, but private batch validation is unavailable: "
                f"{batch_warning}"
            )
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="extension_upload",
                result="success",
                safe_detail=(
                    "Installed reviewed local files: "
                    + ", ".join(
                        f"{entry.file_name} (sha256 {entry.sha256 or 'unknown'})"
                        for entry in entries
                    )
                ),
            )
        )
        db.commit()
        return {
            "installed": [entry.model_dump() for entry in entries],
            "destination": extension_dir.name,
            "restart_required": True,
            "source_verified": False,
            "batch_id": batch_id,
            "warnings": warnings,
        }

    @app.delete(
        "/api/v1/profiles/{profile_id}/extensions/manual-import/{review_id}",
        status_code=204,
    )
    def manual_import_cancel(profile_id: str, review_id: str, request: Request, db: Db) -> None:
        mutation(request, db)
        _, extension_dir = extension_context(profile_id, db)
        if not re.fullmatch(r"[0-9a-f]{16}", review_id):
            raise HTTPException(404, "That manual import review was not found.")
        shutil.rmtree(extension_dir / f".blockstead-manual-{review_id}", ignore_errors=True)

    @app.post("/api/v1/profiles/{profile_id}/loadout/test-start")
    async def loadout_test_start(
        profile_id: str,
        payload: SafeTestStartRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        directory = profile_directory(profile_id, db)
        cleanup_validation_workspaces(directory)
        cleanup_reviewed_batches(extension_dir)
        run_id = secrets.token_hex(8)
        reviewed_batch = None
        ignored_batches = 0
        if payload.recent_batch_ids and payload.retry_of is None:
            ignored_batches = max(0, len(payload.recent_batch_ids) - 1)
            try:
                reviewed_batch = load_reviewed_batch(extension_dir, payload.recent_batch_ids[-1])
            except SafeStartError as exc:
                raise HTTPException(409, str(exc)) from exc
        try:
            if profile.is_fixture:
                arguments = (
                    sys.executable,
                    str(Path(__file__).with_name("fake_server.py")),
                    "--mode",
                    "normal",
                )
                java_executable = sys.executable
            else:
                required = required_java_major(profile.minecraft_version)
                runtime = find_java(required, discover_java_runtimes())
                if runtime is None:
                    needed = f"Java {required} or newer" if required else "a Java runtime"
                    raise SafeStartError(f"Private validation needs {needed}, but none was found.")
                arguments = None
                java_executable = runtime.path
            plan = plan_safe_test_start(
                profile_id=profile.id,
                distribution=profile.distribution,
                server_directory=directory,
                process_state=manager.state,
                java_executable=java_executable,
                reviewed_batch=reviewed_batch,
                arguments=arguments,
                validation_id=run_id,
            )
            result = await run_safe_test_start(manager, plan)
        except SafeStartError as exc:
            raise HTTPException(409, str(exc)) from exc

        if reviewed_batch is not None and (
            result.status == "passed" or result.quarantine.succeeded
        ):
            try:
                delete_reviewed_batch(extension_dir, reviewed_batch.review_id)
            except SafeStartError:
                pass
        quarantined = [
            {
                "file_name": file_name,
                "reason": result.quarantine.detail
                or "Disabled after the private startup test failed.",
            }
            for file_name in result.quarantine.files
        ]
        warnings = list(result.warnings)
        if ignored_batches:
            warnings.append(
                "Only the most recent reviewed install batch was eligible for automatic quarantine."
            )
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="loadout_validation",
                result="success" if result.status == "passed" else "failed",
                safe_detail=(
                    f"Private loadout validation {result.status}; "
                    f"{len(quarantined)} file(s) quarantined"
                ),
            )
        )
        db.commit()
        return {
            "run_id": run_id,
            "status": result.status,
            "summary": result.detail,
            "failure_kind": result.failure_kind,
            "log_tail": [item.line for item in result.evidence],
            "log_lines_truncated": result.evidence_truncated,
            "quarantined": quarantined,
            "retry_allowed": result.status == "failed" and bool(quarantined),
            "warnings": warnings,
            "duration_ms": result.duration_ms,
            "live_world_untouched": True,
            "validation_workspace_removed": result.validation_workspace_removed,
        }

    def loadout_view(
        profile_id: str, db: Session
    ) -> tuple[Profile, Path, ExtensionsView, OriginMap]:
        profile, extension_dir = extension_context(profile_id, db)
        view = read_extensions(profile_directory(profile_id, db), profile.distribution)
        try:
            origins = load_origin_map(extension_dir)
        except OriginRegistryError:
            origins = {}
        return profile, extension_dir, view, origins

    @app.get("/api/v1/profiles/{profile_id}/loadout/lockfile")
    def loadout_lockfile(profile_id: str, request: Request, db: Db) -> Response:
        current(request, db)
        profile, _, view, origins = loadout_view(profile_id, db)
        if not profile.minecraft_version:
            raise HTTPException(409, "This profile has no recognized Minecraft version.")
        lockfile = build_loadout_lockfile(
            view,
            minecraft_version=profile.minecraft_version,
            distribution=profile.distribution,
            loader_version=profile.loader_version,
            generated_at=datetime.now(UTC),
            origins=origins,
        )
        return Response(
            content=serialize_loadout_lockfile(lockfile),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="blockstead-loadout-{profile.id}.lock.json"'
                )
            },
        )

    @app.post("/api/v1/profiles/{profile_id}/loadout/lockfile/review")
    async def loadout_lockfile_review(
        profile_id: str,
        file: UploadFile,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        mutation(request, db)
        profile, _, view, origins = loadout_view(profile_id, db)
        if not profile.minecraft_version:
            raise HTTPException(409, "This profile has no recognized Minecraft version.")
        content = await file.read(MAX_LOCKFILE_BYTES + 1)
        review = review_loadout_lockfile(
            content,
            view,
            minecraft_version=profile.minecraft_version,
            distribution=profile.distribution,
            loader_version=profile.loader_version,
            origins=origins,
        )
        action_by_code = {
            "missing_extension": "install",
            "extra_extension": "remove",
            "extension_checksum_mismatch": "update",
            "extension_state_mismatch": "keep",
            "extension_metadata_mismatch": "keep",
            "file_name_mismatch": "keep",
        }
        changes = [
            {
                "file_name": mismatch.file_name or "Server setup",
                "action": action_by_code.get(mismatch.code, "unavailable"),
                "detail": mismatch.message,
            }
            for mismatch in review.mismatches
        ]
        expected = review.lockfile
        manual_requirements = (
            [
                item.file_name
                for item in [*expected.installed, *expected.disabled]
                if item.origin.source in {"unknown", "manual", "local"}
            ]
            if expected
            else []
        )
        return {
            "review_id": secrets.token_hex(8),
            "minecraft_version": (
                expected.minecraft_version if expected else profile.minecraft_version
            ),
            "distribution": expected.distribution if expected else profile.distribution,
            "loader_version": expected.loader_version if expected else profile.loader_version,
            "changes": changes,
            "exclusions": [],
            "manual_requirements": manual_requirements,
            "warnings": ["This comparison is review-only. Blockstead did not change this loadout."],
            "blockers": review.blockers,
            "expires_in_seconds": 15 * 60,
            "compatible": review.compatible,
            "mutation_performed": False,
        }

    def build_player_pack_export(profile_id: str, db: Session) -> PlayerPackExportResult:
        profile, _, view, origins = loadout_view(profile_id, db)
        if profile.distribution == "paper":
            raise HTTPException(
                409,
                "Paper plugins run on the server and do not belong in a player mod pack.",
            )
        if not profile.minecraft_version:
            raise HTTPException(409, "This profile has no recognized Minecraft version.")
        try:
            return build_player_mrpack(
                view,
                minecraft_version=profile.minecraft_version,
                distribution=profile.distribution,
                loader_version=profile.loader_version,
                pack_name=f"{profile.name} player pack",
                version_id=f"minecraft-{profile.minecraft_version}",
                summary=f"Client loadout exported from Blockstead profile {profile.name}.",
                generated_at=datetime.now(UTC),
                origins=origins,
            )
        except PlayerPackExportError as exc:
            raise HTTPException(409, str(exc)) from exc

    def player_pack_review_id(exported: PlayerPackExportResult) -> str:
        summary = exported.summary.model_dump(mode="json")
        summary.pop("generated_at", None)
        evidence = {"index": exported.index, "summary": summary}
        return hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]

    @app.get("/api/v1/profiles/{profile_id}/loadout/player-pack/review")
    def loadout_player_pack_review(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        exported = build_player_pack_export(profile_id, db)
        return {
            "review_id": player_pack_review_id(exported),
            "dependencies": exported.index["dependencies"],
            **exported.summary.model_dump(mode="json"),
        }

    @app.get("/api/v1/profiles/{profile_id}/loadout/player-pack")
    def loadout_player_pack(
        profile_id: str,
        request: Request,
        db: Db,
        review_id: str | None = None,
    ) -> Response:
        current(request, db)
        if review_id is not None and not re.fullmatch(r"[0-9a-f]{16}", review_id):
            raise HTTPException(422, "That player-pack review id is invalid.")
        exported = build_player_pack_export(profile_id, db)
        current_review = player_pack_review_id(exported)
        if review_id is not None and review_id != current_review:
            raise HTTPException(
                409,
                "This loadout changed after the player-pack review. Review the pack again.",
            )
        return Response(
            content=exported.archive,
            media_type="application/x-modrinth-modpack+zip",
            headers={
                "Content-Disposition": (f'attachment; filename="{exported.summary.file_name}"'),
                "X-Blockstead-Included": str(len(exported.summary.included)),
                "X-Blockstead-Manual": str(len(exported.summary.manual_requirements)),
                "X-Blockstead-Excluded": str(len(exported.summary.excluded)),
            },
        )

    @app.get("/api/v1/profiles/{profile_id}/configs")
    def profile_configs(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        files = list_mod_configs(profile_directory(profile_id, db))
        return {
            "distribution": profile.distribution,
            "directory": "config",
            "files": [entry.model_dump() for entry in files],
        }

    @app.get("/api/v1/profiles/{profile_id}/configs/file")
    def profile_config_file(
        profile_id: str, path: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        extension_context(profile_id, db)
        try:
            return read_mod_config(profile_directory(profile_id, db), path).model_dump()
        except (ModConfigError, OSError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.put("/api/v1/profiles/{profile_id}/configs/file")
    def update_profile_config(
        profile_id: str,
        payload: ModConfigUpdateRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        extension_context(profile_id, db)
        try:
            document = write_mod_config(
                profile_directory(profile_id, db),
                payload.path,
                payload.revision,
                payload.content,
            )
        except ModConfigError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="mod_config_update",
                result="success",
                safe_detail=f"Updated loader configuration {payload.path}",
            )
        )
        db.commit()
        return {**document.model_dump(), "restart_required": True}

    def file_category(value: str) -> FileCategory:
        if value not in FILE_CATEGORIES:
            raise HTTPException(404, "That file category is not recognized.")
        return cast(FileCategory, value)

    def file_context(profile_id: str, db: Session) -> tuple[Profile, Path]:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        return profile, profile_directory(profile_id, db)

    def require_stopped_for(category: FileCategory) -> None:
        if category in STOPPED_REQUIRED_CATEGORIES:
            require_server_stopped()

    @app.get("/api/v1/profiles/{profile_id}/files/{category}")
    def list_profile_files(
        profile_id: str, category: str, request: Request, db: Db, path: str = ""
    ) -> dict[str, object]:
        current(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        try:
            listing = list_category(
                directory,
                profile.distribution,
                kind,
                path,
                data_dir=config.data_dir,
                profile_id=profile.id,
            )
        except FilePathError as exc:
            raise HTTPException(404, str(exc)) from exc
        return listing.model_dump()

    @app.get("/api/v1/profiles/{profile_id}/files/{category}/content")
    def profile_file_content(
        profile_id: str, category: str, path: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        try:
            content = read_file_content(
                directory,
                profile.distribution,
                kind,
                path,
                data_dir=config.data_dir,
                profile_id=profile.id,
            )
        except FilePathError as exc:
            raise HTTPException(404, str(exc)) from exc
        return content.model_dump()

    @app.get("/api/v1/profiles/{profile_id}/files/{category}/download")
    def download_profile_file(
        profile_id: str, category: str, path: str, request: Request, db: Db
    ) -> FileResponse:
        admin, _ = current(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        try:
            target = resolve_download_path(
                directory,
                profile.distribution,
                kind,
                path,
                data_dir=config.data_dir,
                profile_id=profile.id,
            )
        except FilePathError as exc:
            raise HTTPException(404, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_download",
                result="success",
                safe_detail=f"Downloaded {kind}/{path}",
            )
        )
        db.commit()
        return FileResponse(target, filename=target.name)

    @app.post("/api/v1/profiles/{profile_id}/files/{category}/content/preview")
    def preview_profile_file_edit(
        profile_id: str, category: str, payload: FileEditRequest, request: Request, db: Db
    ) -> dict[str, object]:
        mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        try:
            preview = preview_file_edit(
                directory,
                profile.distribution,
                kind,
                payload.path,
                payload.revision,
                payload.content,
                data_dir=config.data_dir,
                profile_id=profile.id,
            )
        except FileConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FilePathError as exc:
            raise HTTPException(409, str(exc)) from exc
        return preview.model_dump()

    @app.put("/api/v1/profiles/{profile_id}/files/{category}/content")
    def apply_profile_file_edit(
        profile_id: str, category: str, payload: FileEditRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        require_stopped_for(kind)
        try:
            result = apply_file_edit(
                directory,
                profile.distribution,
                kind,
                payload.path,
                payload.revision,
                payload.content,
                config.data_dir,
                profile.id,
                data_dir=config.data_dir,
            )
        except FileConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FilePathError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_edit",
                result="success",
                safe_detail=(
                    f"Edited {kind}/{payload.path}; recovery snapshot {result.snapshot_name}"
                ),
            )
        )
        db.commit()
        return result.model_dump()

    @app.post("/api/v1/profiles/{profile_id}/files/{category}/rename")
    def rename_profile_file(
        profile_id: str, category: str, payload: FileRenameRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        require_stopped_for(kind)
        try:
            result = rename_file(
                directory,
                profile.distribution,
                kind,
                payload.path,
                payload.new_name,
                data_dir=config.data_dir,
                profile_id=profile.id,
            )
        except FilePathError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_rename",
                result="success",
                safe_detail=f"Renamed {kind}/{payload.path} to {result.path}",
            )
        )
        db.commit()
        return result.model_dump()

    @app.delete("/api/v1/profiles/{profile_id}/files/{category}")
    def delete_profile_file(
        profile_id: str, category: str, path: str, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        require_stopped_for(kind)
        try:
            result = delete_file(
                directory,
                profile.distribution,
                kind,
                path,
                config.data_dir,
                profile.id,
                datetime.now(timezone.utc),  # noqa: UP017
                data_dir=config.data_dir,
            )
        except FilePathError as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_delete",
                result="success",
                safe_detail=(
                    f"Deleted {kind}/{path}; "
                    + (
                        f"recovery snapshot {result.snapshot_name}"
                        if result.snapshot_name
                        else f"preserved as {result.preserved_name}"
                    )
                ),
            )
        )
        db.commit()
        return result.model_dump()

    @app.post("/api/v1/profiles/{profile_id}/files/{category}/upload")
    async def upload_profile_files(
        profile_id: str,
        category: str,
        files: list[UploadFile],
        request: Request,
        db: Db,
        path: str = Form(""),
    ) -> dict[str, object]:
        admin = mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        require_stopped_for(kind)
        if len(files) > 100:
            raise HTTPException(400, "Send the upload in smaller batches of files.")
        free_margin = 1 << 30
        budget = psutil.disk_usage(str(directory)).free - free_margin
        written = 0
        uploaded: list[str] = []
        for file in files:
            try:
                target = resolve_upload_target(
                    directory,
                    profile.distribution,
                    kind,
                    path,
                    file.filename or "",
                    data_dir=config.data_dir,
                    profile_id=profile.id,
                )
            except FilePathError as exc:
                raise HTTPException(409, str(exc)) from exc
            staging = target.with_name(f".{target.name}.{secrets.token_hex(8)}.part")
            try:
                with staging.open("wb") as output:
                    while chunk := await file.read(1 << 20):
                        written += len(chunk)
                        if written > budget:
                            raise HTTPException(
                                409,
                                "The computer does not have enough free disk space "
                                "for this upload. Free some space and try again.",
                            )
                        output.write(chunk)
                staging.replace(target)
            except OSError as exc:
                raise HTTPException(409, "The uploaded file could not be written.") from exc
            finally:
                staging.unlink(missing_ok=True)
            uploaded.append(file.filename or target.name)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_upload",
                result="success",
                safe_detail=f"Uploaded {len(uploaded)} file(s) to {kind}/{path}",
            )
        )
        db.commit()
        return {"uploaded": uploaded, "received_bytes": written}

    @app.post("/api/v1/profiles/{profile_id}/files/{category}/archive/extract")
    async def extract_profile_archive(
        profile_id: str,
        category: str,
        file: UploadFile,
        request: Request,
        db: Db,
        path: str = Form(""),
    ) -> dict[str, object]:
        admin = mutation(request, db)
        kind = file_category(category)
        profile, directory = file_context(profile_id, db)
        require_stopped_for(kind)
        if profile.id in extracting_profiles:
            raise HTTPException(
                409, "An archive extraction is already in progress for this server."
            )
        tmp_dir = config.data_dir / "file-uploads-tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive_path = tmp_dir / f"{profile.id}-{secrets.token_hex(8)}.zip"
        free_margin = 1 << 30
        budget = psutil.disk_usage(str(directory)).free - free_margin
        written = 0
        extracting_profiles.add(profile.id)
        try:
            with archive_path.open("wb") as output:
                while chunk := await file.read(1 << 20):
                    written += len(chunk)
                    if written > budget:
                        raise HTTPException(
                            409,
                            "The computer does not have enough free disk space "
                            "for this archive. Free some space and try again.",
                        )
                    output.write(chunk)
            try:
                result = await asyncio.to_thread(
                    extract_archive_into,
                    directory,
                    profile.distribution,
                    kind,
                    path,
                    archive_path,
                    datetime.now(timezone.utc),  # noqa: UP017
                    data_dir=config.data_dir,
                    profile_id=profile.id,
                )
            except FilePathError as exc:
                raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "The uploaded archive could not be written.") from exc
        finally:
            archive_path.unlink(missing_ok=True)
            extracting_profiles.discard(profile.id)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="file_archive_extract",
                result="success",
                safe_detail=(
                    f"Extracted archive into {kind}/{path}: "
                    f"{len(result.promoted)} item(s) added"
                    + (f", {len(result.preserved)} preserved" if result.preserved else "")
                ),
            )
        )
        db.commit()
        return result.model_dump()

    @app.get("/api/v1/modpacks/search")
    async def modpack_search(query: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        if not query.strip() or len(query) > 100:
            raise HTTPException(422, "Enter a search of at most 100 characters.")
        try:
            projects = await search_modpacks(http_client, query.strip())
        except ModrinthError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"projects": [project.model_dump() for project in projects]}

    def record_modpack_profile(
        admin: Administrator,
        db: Session,
        name: str,
        result_directory: str,
        distribution: str,
        version: str,
        loader_version: str | None,
    ) -> Profile:
        profile = Profile(
            name=name.strip(),
            server_directory=result_directory,
            distribution=distribution,
            minecraft_version=version,
            loader_version=loader_version,
            is_fixture=False,
        )
        db.add(profile)
        db.flush()
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="modpack_install",
                result="success",
                safe_detail=f"Imported modpack into {result_directory}",
            )
        )
        db.commit()
        return profile

    @app.post("/api/v1/modpacks/install", status_code=201)
    async def modpack_install(
        payload: ModpackInstallRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        try:
            data = await fetch_mrpack(http_client, payload.project_id, payload.version_id)
            result = await install_modpack(
                http_client, config.server_root, payload.directory_name, data
            )
        except (ModpackError, ModrinthError, ProvisionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "The new server folder could not be created.") from exc
        profile = record_modpack_profile(
            admin,
            db,
            payload.name,
            result.directory,
            result.distribution,
            result.minecraft_version,
            result.loader_version,
        )
        return {
            "id": profile.id,
            "name": profile.name,
            **result.model_dump(),
            "eula_accepted": False,
        }

    @app.post("/api/v1/modpacks/upload", status_code=201)
    async def modpack_upload(
        request: Request,
        db: Db,
        file: UploadFile,
        name: str = Form(min_length=1, max_length=80),
        directory_name: str = Form(min_length=1, max_length=64),
    ) -> dict[str, object]:
        admin = mutation(request, db)
        data = await file.read(MAX_MRPACK_BYTES + 1)
        try:
            result = await install_modpack(http_client, config.server_root, directory_name, data)
        except (ModpackError, ModrinthError, ProvisionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(409, "The new server folder could not be created.") from exc
        profile = record_modpack_profile(
            admin,
            db,
            name,
            result.directory,
            result.distribution,
            result.minecraft_version,
            result.loader_version,
        )
        return {
            "id": profile.id,
            "name": profile.name,
            **result.model_dump(),
            "eula_accepted": False,
        }

    @app.get("/api/v1/profiles/{profile_id}/prerequisites")
    def profile_prerequisites(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        required = None if profile.is_fixture else required_java_major(profile.minecraft_version)
        runtimes = [] if profile.is_fixture else discover_java_runtimes()
        selected = find_java(required, runtimes)
        launch_problem: str | None = None
        if not profile.is_fixture:
            if profile.distribution == "unknown":
                launch_problem = "The distribution of this server folder was not recognized."
            else:
                try:
                    launch_arguments(profile.distribution, directory)
                except LaunchPlanError as exc:
                    launch_problem = str(exc)
        extension = info.extension_directory
        return {
            "distribution": profile.distribution,
            "label": info.label,
            "minecraft_version": profile.minecraft_version,
            "is_fixture": profile.is_fixture,
            "eula_accepted": profile.is_fixture or eula_accepted(directory),
            "required_java_major": required,
            "java_runtimes": [runtime.model_dump() for runtime in runtimes],
            "selected_java": selected.model_dump() if selected else None,
            "java_satisfied": profile.is_fixture or selected is not None,
            "launch_files_ready": launch_problem is None,
            "launch_problem": launch_problem,
            "extension_directory": extension,
            "extension_directory_present": bool(extension)
            and (directory / str(extension)).is_dir(),
        }

    @app.get("/api/v1/profiles/{profile_id}/overview")
    async def profile_overview(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        properties = read_properties(directory)
        active = app.state.active_profile_id == profile.id
        snapshot = manager.snapshot()
        state = str(snapshot["state"]) if active else "STOPPED"
        if state.startswith("ProcessState."):
            state = state.removeprefix("ProcessState.")

        latest_sample = db.scalar(
            select(MetricSample)
            .where(MetricSample.profile_id == profile.id)
            .order_by(MetricSample.created_at.desc())
            .limit(1)
        )
        now_utc = datetime.now(timezone.utc)  # noqa: UP017
        latest_at = latest_sample.created_at if latest_sample else None
        if latest_at is not None and latest_at.tzinfo is None:
            latest_at = latest_at.replace(tzinfo=timezone.utc)  # noqa: UP017
        if latest_at is None or now_utc - latest_at >= timedelta(seconds=50):
            sample = await asyncio.to_thread(collect_metric_sample, profile, include_process=active)
            db.add(sample)
            db.commit()

        samples = list(
            reversed(
                db.scalars(
                    select(MetricSample)
                    .where(MetricSample.profile_id == profile.id)
                    .order_by(MetricSample.created_at.desc())
                    .limit(72)
                ).all()
            )
        )

        def sample_payload(sample: MetricSample) -> dict[str, object]:
            created = sample.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)  # noqa: UP017
            return {
                "at": created.astimezone(timezone.utc).isoformat(),  # noqa: UP017
                "cpu_percent": sample.cpu_percent,
                "memory_percent": sample.memory_percent,
                "disk_percent": sample.disk_percent,
                "process_memory_bytes": sample.process_memory_bytes,
                "world_size_bytes": sample.world_size_bytes,
            }

        live_sample = samples[-1]
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(config.data_dir))
        uptime: float | None = None
        if active and manager.started_at is not None:
            uptime = max(0.0, (now_utc - manager.started_at).total_seconds())

        public_ip = await app.state.public_ip_discovery.discover()
        join = join_details(properties, public_ip)
        status_probe = (
            await minecraft_status_probe(properties) if active and state == "RUNNING" else None
        )
        if status_probe is not None:
            remember_status_probe(profile.id, cast(dict[str, object], status_probe))
        status = status_probe["status"] if status_probe is not None else None
        if active and state == "RUNNING":
            await sample_performance(profile)
        latest_performance = db.scalar(
            select(PerformanceSample)
            .where(PerformanceSample.profile_id == profile.id)
            .order_by(PerformanceSample.created_at.desc())
            .limit(1)
        )
        configured_max = 20
        try:
            possible_max = int(properties.get("max-players", "20"))
            if 1 <= possible_max <= 1000:
                configured_max = possible_max
        except ValueError:
            pass
        players = status or {"online": None, "max": configured_max, "sample": []}
        players["available"] = status is not None
        players["status_outcome"] = (
            status_probe["outcome"] if status_probe is not None else "not_running"
        )
        players["status_detail"] = (
            status_probe["detail"]
            if status_probe is not None
            else "Player and server-list status is checked while this server is running."
        )

        backup = db.scalar(
            select(BackupRecord)
            .where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "completed",
            )
            .order_by(BackupRecord.created_at.desc())
            .limit(1)
        )
        schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile.id))
        pending_events = db.scalars(
            select(AutomationEvent).where(
                AutomationEvent.profile_id == profile.id,
                AutomationEvent.completed_at.is_(None),
            )
        ).all()
        upcoming = next_executions(schedule, pending_events, datetime.now().astimezone(), limit=1)
        next_operation = (
            {"label": upcoming[0]["label"], "at": upcoming[0]["at"]} if upcoming else None
        )

        warnings: list[dict[str, str]] = []
        if state == "RUNNING" and latest_performance is not None:
            low_tps = (
                latest_performance.tps_one_minute is not None
                and latest_performance.tps_one_minute < 19.0
            )
            high_mspt = (
                latest_performance.mspt_five_seconds is not None
                and latest_performance.mspt_five_seconds > 50.0
            )
            if low_tps or high_mspt:
                warnings.append(
                    {
                        "code": "performance-evidence",
                        "title": "Tick performance needs a closer look",
                        "detail": (
                            "Recent Paper tick evidence crossed the normal 20 TPS / 50 MSPT "
                            "threshold. Capture a bounded local Spark profile before "
                            "changing settings."
                        ),
                        "to": f"/servers/{profile.id}/overview#performance-heading",
                        "severity": "warning",
                    }
                )
        if state in {"CRASHED", "DEGRADED"}:
            warnings.append(
                {
                    "code": "server-state",
                    "title": "Server needs attention",
                    "detail": str(snapshot["reason"]),
                    "to": f"/servers/{profile.id}/console",
                    "severity": "danger",
                }
            )
        if status_probe is not None and status_probe["outcome"] in {
            "timeout",
            "unreachable",
            "invalid_bind",
            "invalid_response",
        }:
            warnings.append(
                {
                    "code": "local-status",
                    "title": "Minecraft's local status check needs attention",
                    "detail": status_probe["detail"],
                    "to": f"/help?profile={profile.id}#server-troubleshooter",
                    "severity": "warning",
                }
            )
        if disk.percent >= 90:
            warnings.append(
                {
                    "code": "disk-space",
                    "title": "Storage is running low",
                    "detail": f"The Blockstead data disk is {disk.percent:.0f}% full.",
                    "to": "/system",
                    "severity": "danger" if disk.percent >= 95 else "warning",
                }
            )
        if backup is None:
            warnings.append(
                {
                    "code": "backup-missing",
                    "title": "This world has not been backed up",
                    "detail": "Create a verified backup before making important changes.",
                    "to": f"/servers/{profile.id}/backups",
                    "severity": "warning",
                }
            )
        else:
            backup_at = backup.created_at
            if backup_at.tzinfo is None:
                backup_at = backup_at.replace(tzinfo=timezone.utc)  # noqa: UP017
            if now_utc - backup_at > timedelta(days=7):
                warnings.append(
                    {
                        "code": "backup-stale",
                        "title": "The latest backup is over a week old",
                        "detail": "Create a fresh backup to keep recovery current.",
                        "to": f"/servers/{profile.id}/backups",
                        "severity": "warning",
                    }
                )
        if join["local_only"]:
            warnings.append(
                {
                    "code": "local-bind",
                    "title": "Only this computer can join",
                    "detail": "The server is bound to a loopback address in server.properties.",
                    "to": f"/servers/{profile.id}/settings",
                    "severity": "warning",
                }
            )
        if join["public"]["state"] == "unavailable":
            warnings.append(
                {
                    "code": "public-address-unavailable",
                    "title": "Public Minecraft address could not be detected",
                    "detail": "Blockstead is not showing a guessed public address.",
                    "to": f"/servers/{profile.id}/overview#connection-help",
                    "severity": "warning",
                }
            )

        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        required = None if profile.is_fixture else required_java_major(profile.minecraft_version)
        runtimes = [] if profile.is_fixture else discover_java_runtimes()
        selected = find_java(required, runtimes)
        launch_problem: str | None = None
        if not profile.is_fixture:
            if profile.distribution == "unknown":
                launch_problem = "The server distribution was not recognized."
            else:
                try:
                    launch_arguments(profile.distribution, directory)
                except LaunchPlanError as exc:
                    launch_problem = str(exc)
        if launch_problem:
            warnings.append(
                {
                    "code": "launch-files",
                    "title": "Launcher needs attention",
                    "detail": launch_problem,
                    "to": f"/servers/{profile.id}/overview#readiness",
                    "severity": "warning",
                }
            )
        if not profile.is_fixture and selected is None:
            warnings.append(
                {
                    "code": "java-runtime",
                    "title": f"Java {required or 'runtime'} is needed",
                    "detail": "Install a compatible Java runtime before starting this server.",
                    "to": f"/servers/{profile.id}/overview#readiness",
                    "severity": "warning",
                }
            )
        if not profile.is_fixture and not eula_accepted(directory):
            warnings.append(
                {
                    "code": "eula",
                    "title": "Minecraft EULA acceptance is required",
                    "detail": "Review and accept the EULA before the first launch.",
                    "to": f"/servers/{profile.id}/overview#readiness",
                    "severity": "warning",
                }
            )

        category_links = {
            "manual_backup": "backups",
            "backup_restore": "backups",
            "backup_recovery_drill": "backups",
            "backup_destination_check": "world-care",
            "world_cleanup": "world-care",
            "diagnostic_capture": "overview",
            "backup_policy": "backups",
            "server_start": "console",
            "server_restart": "console",
            "console_command": "console",
            "player_action": "players",
            "settings_update": "settings",
            "settings_raw_update": "settings",
            "schedule_update": "schedule",
            "extension_install": "mods",
            "extension_toggle": "mods",
            "extension_delete": "mods",
            "extension_upload": "mods",
            "shared_map_profile": "mods",
            "mod_config_update": "mods",
        }
        activity: list[dict[str, str]] = []
        events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(50))
        for event in events:
            if event.profile_id != profile.id and (
                event.profile_id is not None
                or (profile.id not in event.safe_detail and profile.name not in event.safe_detail)
            ):
                continue
            created = event.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)  # noqa: UP017
            section = category_links.get(event.category, "overview")
            activity.append(
                {
                    "id": event.id,
                    "category": event.category,
                    "result": event.result,
                    "detail": event.safe_detail,
                    "created_at": created.astimezone(timezone.utc).isoformat(),  # noqa: UP017
                    "to": f"/servers/{profile.id}/{section}",
                }
            )
            if len(activity) == 5:
                break

        backup_payload_value = backup_payload(backup) if backup else None
        performance_supported = performance_capable(profile.distribution)
        performance_sampled_at: str | None = None
        if latest_performance is not None:
            sampled_at = latest_performance.created_at
            if sampled_at.tzinfo is None:
                sampled_at = sampled_at.replace(tzinfo=timezone.utc)  # noqa: UP017
            performance_sampled_at = sampled_at.astimezone(timezone.utc).isoformat()  # noqa: UP017
        if not performance_supported:
            performance_detail = (
                f"{info.label} does not expose a supported Blockstead TPS/MSPT source. "
                "These values are omitted rather than guessed."
            )
            performance_state = "unsupported"
        elif state != "RUNNING":
            performance_detail = (
                "Performance sampling is available while this Paper server is running. "
                "No current value is being claimed while it is stopped."
            )
            performance_state = "not_running"
        elif latest_performance is None:
            performance_detail = "Waiting for the first bounded Paper performance response."
            performance_state = "waiting"
        else:
            performance_detail = latest_performance.detail
            performance_values = (
                latest_performance.tps_one_minute is not None
                and latest_performance.mspt_five_seconds is not None
            )
            performance_state = "available" if performance_values else "partial"
        current_metrics: dict[str, object] = sample_payload(live_sample)
        current_metrics.update(
            {
                "memory_used_bytes": memory.used,
                "memory_total_bytes": memory.total,
                "disk_used_bytes": disk.used,
                "disk_total_bytes": disk.total,
            }
        )
        return {
            "state": {
                "value": state,
                "reason": snapshot["reason"] if active else "This server is not running.",
                "uptime_seconds": uptime,
            },
            "join": join,
            "players": players,
            "metrics": {
                "current": current_metrics,
                "history": [sample_payload(sample) for sample in samples],
            },
            "last_backup": backup_payload_value,
            "next_operation": next_operation,
            "warnings": warnings,
            "activity": activity,
            "performance": {
                "state": performance_state,
                "available": performance_state == "available",
                "source": PERFORMANCE_SOURCE if performance_supported else None,
                "sampling_period_seconds": (
                    PERFORMANCE_SAMPLING_PERIOD_SECONDS if performance_supported else None
                ),
                "sampled_at": performance_sampled_at,
                "tps": (
                    {
                        "one_minute": latest_performance.tps_one_minute,
                        "five_minutes": latest_performance.tps_five_minutes,
                        "fifteen_minutes": latest_performance.tps_fifteen_minutes,
                    }
                    if latest_performance is not None
                    and performance_state in {"available", "partial"}
                    else None
                ),
                "mspt": (
                    {
                        "five_seconds": latest_performance.mspt_five_seconds,
                        "ten_seconds": latest_performance.mspt_ten_seconds,
                        "sixty_seconds": latest_performance.mspt_sixty_seconds,
                    }
                    if latest_performance is not None
                    and performance_state in {"available", "partial"}
                    else None
                ),
                "detail": performance_detail,
            },
            "capabilities": {
                "tps": performance_supported,
                "mspt": performance_supported,
                "distribution_label": info.label,
            },
        }

    def destination_check_payload(record: BackupDestinationCheck) -> dict[str, object]:
        checked_at = record.checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=UTC)
        return {
            "state": record.state,
            "write_verified": record.write_verified,
            "read_verified": record.read_verified,
            "detail": record.detail,
            "checked_at": checked_at.astimezone(UTC).isoformat(),
        }

    def verified_cleanup_backup(profile: Profile, db: Session) -> BackupRecord | None:
        """Return one locally verified archive; cleanup never relies on a claim alone."""

        records = db.scalars(
            select(BackupRecord)
            .where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "completed",
            )
            .order_by(BackupRecord.created_at.desc())
        ).all()
        for record in records:
            if not record.file_name or not record.manifest_name:
                continue
            try:
                verify_backup_archive(
                    config.data_dir,
                    profile.id,
                    record.file_name,
                    record.manifest_name,
                    record.sha256,
                )
            except RestoreError:
                continue
            return record
        return None

    def cleanup_plan_payload(
        plan: ReviewedCleanupPlan | None,
        *,
        candidates: list[CleanupTarget],
        blockers: list[str],
        recovery: list[dict[str, object]],
    ) -> dict[str, object]:
        targets = list(plan.targets) if plan is not None else candidates
        return {
            "plan_id": plan.id if plan is not None else None,
            "created_at": plan.created_at.astimezone(UTC).isoformat() if plan else None,
            "expires_at": plan.expires_at.astimezone(UTC).isoformat() if plan else None,
            "can_apply": plan is not None and not blockers and bool(plan.targets),
            "blockers": blockers,
            "targets": [
                {
                    "path": target.relative_path,
                    "label": target.label,
                    "size_bytes": target.size_bytes,
                    "reason": target.reason,
                    "recovery_effect": target.recovery_effect,
                }
                for target in targets
            ],
            "protected": [
                {
                    "label": entry["label"],
                    "detail": "Recovery copies are never included in automatic cleanup.",
                }
                for entry in recovery
            ],
        }

    @app.get("/api/v1/profiles/{profile_id}/world-care/cleanup-plan")
    def review_world_cleanup(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        """Build an exact, short-lived review for safe private-data cleanup."""

        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        now = datetime.now(UTC)
        for plan_id, expired_plan in tuple(reviewed_cleanup_plans.items()):
            if expired_plan.expires_at <= now:
                reviewed_cleanup_plans.pop(plan_id, None)
        expired = db.scalars(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "expired",
            )
        ).all()
        candidates = cleanup_candidates(
            config.data_dir,
            profile.id,
            [(record.file_name, record.manifest_name) for record in expired],
            now,
        )
        recovery = recovery_snapshot_entries(directory, config.data_dir, profile.id)
        blockers: list[str] = []
        pending = db.scalar(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "in_progress",
            )
        )
        if pending is not None:
            blockers.append("Wait for the active backup to finish before reviewing cleanup.")
        if profile.id in recovery_drill_profiles:
            blockers.append(
                "Wait for the active recovery drill to finish before reviewing cleanup."
            )
        verified = verified_cleanup_backup(profile, db)
        if verified is None:
            blockers.append("Create a locally verified backup before removing any artifact.")
        plan: ReviewedCleanupPlan | None = None
        if candidates and not blockers and verified is not None:
            plan = ReviewedCleanupPlan(
                id=secrets.token_hex(16),
                profile_id=profile.id,
                created_at=now,
                expires_at=now + timedelta(minutes=15),
                targets=tuple(candidates),
                verified_backup_id=verified.id,
            )
            reviewed_cleanup_plans[plan.id] = plan
        return cleanup_plan_payload(
            plan,
            candidates=candidates,
            blockers=blockers,
            recovery=recovery,
        )

    @app.post("/api/v1/profiles/{profile_id}/world-care/cleanup-plan/{plan_id}/apply")
    async def apply_world_cleanup(
        profile_id: str,
        plan_id: str,
        payload: CleanupApplyRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        plan = reviewed_cleanup_plans.get(plan_id)
        now = datetime.now(UTC)
        if plan is None or plan.profile_id != profile_id or plan.expires_at <= now:
            reviewed_cleanup_plans.pop(plan_id, None)
            raise HTTPException(
                409, "That cleanup review expired. Build a fresh plan before removing files."
            )
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        pending = db.scalar(
            select(BackupRecord).where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "in_progress",
            )
        )
        if pending is not None or profile.id in recovery_drill_profiles:
            raise HTTPException(
                409, "Cleanup is unavailable while a backup or recovery drill is in progress."
            )
        verified = verified_cleanup_backup(profile, db)
        if verified is None or verified.id != plan.verified_backup_id:
            raise HTTPException(
                409,
                "The verified backup changed. Build a fresh cleanup review before removing files.",
            )
        try:
            removed = await asyncio.to_thread(
                remove_cleanup_targets, config.data_dir, list(plan.targets)
            )
        except OSError as exc:
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="world_cleanup",
                    result="failed",
                    safe_detail=f"Cleanup refused for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        target_paths = {target.relative_path for target in plan.targets}
        for capture in db.scalars(
            select(DiagnosticCapture).where(DiagnosticCapture.profile_id == profile.id)
        ):
            if capture.output_file in target_paths:
                capture.status = "expired"
                capture.detail = (
                    "The local diagnostic transcript was removed through reviewed cleanup."
                )
        reviewed_cleanup_plans.pop(plan.id, None)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="world_cleanup",
                result="success",
                safe_detail=(
                    f"Removed {removed} reviewed incomplete or expired private artifact(s) for "
                    f"{profile.name}; worlds and recovery copies were not included"
                ),
            )
        )
        db.commit()
        return {
            "removed": removed,
            "result": (
                f"Removed {removed} reviewed private artifact(s). No world, completed backup, "
                "or recovery copy was included."
            ),
        }

    @app.post("/api/v1/profiles/{profile_id}/backup-destinations/check")
    async def check_backup_destinations(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        """Test each approved destination with a private write/read/remove nonce."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        primary = backup_directory(config.data_dir, profile.id)
        destinations: list[tuple[str, str, Path, Path]] = [
            ("Blockstead local backup storage", str(primary), primary, config.data_dir)
        ]
        for raw in configured_backup_destinations(profile):
            root = Path(raw)
            destinations.append(
                (
                    "Approved backup destination",
                    raw,
                    root / "blockstead-backups" / profile.id,
                    root,
                )
            )
        results = await asyncio.gather(
            *[
                asyncio.to_thread(check_backup_destination, target, root)
                for _, _, target, root in destinations
            ]
        )
        checked_at = datetime.now(UTC)
        payloads: list[dict[str, object]] = []
        destination_available: list[bool] = []
        for (label, configured_path, _, _), result in zip(destinations, results, strict=True):
            db.execute(
                delete(BackupDestinationCheck).where(
                    BackupDestinationCheck.profile_id == profile.id,
                    BackupDestinationCheck.destination_path == configured_path,
                )
            )
            record = BackupDestinationCheck(
                profile_id=profile.id,
                destination_path=configured_path,
                label=label,
                state=str(result["state"]),
                write_verified=bool(result["write_verified"]),
                read_verified=bool(result["read_verified"]),
                detail=str(result["detail"]),
                checked_at=checked_at,
            )
            db.add(record)
            destination_available.append(result["state"] == "available")
            payloads.append(
                {
                    "label": label,
                    "configured_path": configured_path,
                    "last_check": {
                        **result,
                        "checked_at": checked_at.isoformat(),
                    },
                }
            )
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="backup_destination_check",
                result=(
                    "success"
                    if all(destination_available)
                    else "warning"
                ),
                safe_detail=(
                    f"Tested {len(payloads)} backup destination(s) with private temporary "
                    "write/read/remove evidence"
                ),
            )
        )
        db.commit()
        return {"destinations": payloads}

    def diagnostic_capture_payload(record: DiagnosticCapture) -> dict[str, object]:
        def timestamp(value: datetime | None) -> str | None:
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat()

        output_available = False
        if record.output_file:
            try:
                resolve_capture_path(config.data_dir, record.profile_id, record.output_file)
                output_available = True
            except DiagnosticCaptureError:
                pass
        return {
            "id": record.id,
            "profile_id": record.profile_id,
            "source": record.source,
            "kind": record.kind,
            "duration_seconds": record.duration_seconds,
            "status": record.status,
            "size_bytes": record.size_bytes,
            "detail": record.detail,
            "created_at": timestamp(record.created_at),
            "completed_at": timestamp(record.completed_at),
            "output_available": output_available,
            "download_url": (
                f"/api/v1/profiles/{record.profile_id}/diagnostic-captures/{record.id}/download"
                if output_available
                else None
            ),
        }

    async def log_lines_after(
        profile_id: str, after_sequence: int, timeout_seconds: float
    ) -> list[str]:
        deadline = time.monotonic() + timeout_seconds
        lines: list[str] = []
        seen: set[int] = set()
        while True:
            for event in manager.logs():
                if (
                    event.sequence > after_sequence
                    and event.sequence not in seen
                    and event.profile_id == profile_id
                ):
                    seen.add(event.sequence)
                    lines.append(event.line)
            if time.monotonic() >= deadline:
                return lines
            await asyncio.sleep(0.05)

    def profiler_is_confirmed_idle(lines: list[str]) -> bool:
        joined = "\n".join(lines).casefold()
        return bool(
            re.search(r"(?:no|not)\s+(?:spark\s+)?profiler.*(?:active|running)", joined)
            or re.search(r"(?:profiler).*(?:not\s+running|inactive)", joined)
        )

    @app.get("/api/v1/profiles/{profile_id}/diagnostic-captures")
    def list_diagnostic_captures(
        profile_id: str, request: Request, db: Db
    ) -> list[dict[str, object]]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        captures = db.scalars(
            select(DiagnosticCapture)
            .where(DiagnosticCapture.profile_id == profile.id)
            .order_by(DiagnosticCapture.created_at.desc())
            .limit(20)
        ).all()
        return [diagnostic_capture_payload(capture) for capture in captures]

    @app.get("/api/v1/profiles/{profile_id}/diagnostic-captures/{capture_id}/download")
    def download_diagnostic_capture(
        profile_id: str, capture_id: str, request: Request, db: Db
    ) -> FileResponse:
        current(request, db)
        capture = db.get(DiagnosticCapture, capture_id)
        if capture is None or capture.profile_id != profile_id or not capture.output_file:
            raise HTTPException(404, "That local diagnostic capture was not found.")
        try:
            output = resolve_capture_path(config.data_dir, profile_id, capture.output_file)
        except DiagnosticCaptureError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(
            output,
            filename=f"blockstead-spark-profile-{capture.id[:8]}.txt",
            media_type="text/plain; charset=utf-8",
        )

    @app.post("/api/v1/profiles/{profile_id}/diagnostic-captures", status_code=201)
    async def create_diagnostic_capture(
        profile_id: str,
        payload: DiagnosticCaptureRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Run a bounded Spark profiler and retain only local owner evidence."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        if not performance_capable(profile.distribution):
            raise HTTPException(
                409,
                "This profile does not expose Blockstead's supported Spark profiler capability.",
            )
        snapshot = manager.snapshot()
        if app.state.active_profile_id != profile.id or snapshot["state"] != "RUNNING":
            raise HTTPException(
                409, "Start this Paper server before capturing a performance profile."
            )
        if profile.id in diagnostic_capture_profiles:
            raise HTTPException(409, "A diagnostic capture is already in progress for this server.")

        capture = DiagnosticCapture(
            profile_id=profile.id,
            source="Paper bundled spark profiler",
            kind="spark_profiler",
            duration_seconds=payload.duration_seconds,
            status="in_progress",
            detail="Checking whether Spark is idle before starting a bounded local profile.",
            created_at=datetime.now(UTC),
        )
        db.add(capture)
        db.commit()
        diagnostic_capture_profiles.add(profile.id)
        profiler_started = False
        try:
            async with performance_lock:
                before_info = manager.logs()[-1].sequence if manager.logs() else 0
                await manager.command("spark profiler info")
                info_lines = await log_lines_after(profile.id, before_info, 1.0)
                if not profiler_is_confirmed_idle(info_lines):
                    raise ValueError(
                        "Blockstead could not confirm that Spark's profiler is idle. "
                        "Stop or cancel any existing Spark profile first."
                    )

                before_profile = manager.logs()[-1].sequence if manager.logs() else before_info
                await manager.command("spark profiler start")
                profiler_started = True
                start_lines = await log_lines_after(profile.id, before_profile, 1.0)
                start_text = "\n".join(start_lines).casefold()
                if "already running" in start_text or "could not start" in start_text:
                    raise ValueError("Spark did not start a new profiler for this capture.")

                await asyncio.sleep(payload.duration_seconds)
                before_stop = manager.logs()[-1].sequence if manager.logs() else before_profile
                await manager.command("spark profiler stop --save-to-file")
                profiler_started = False
                stop_lines = await log_lines_after(profile.id, before_stop, 2.0)
                raw_lines = [*info_lines, *start_lines, *stop_lines][-500:]
                transcript = "\n".join(
                    [
                        "Blockstead local Spark profiler capture",
                        f"Profile: {profile.name}",
                        f"Duration: {payload.duration_seconds} seconds",
                        "Spark was stopped with --save-to-file; no viewer upload was requested.",
                        "",
                        *raw_lines,
                        "",
                    ]
                )
                output_file, size_bytes = await asyncio.to_thread(
                    write_transcript,
                    config.data_dir,
                    profile.id,
                    capture.id,
                    transcript,
                )
                capture.status = "completed"
                capture.output_file = output_file
                capture.size_bytes = size_bytes
                capture.detail = (
                    "Spark was profiled for the selected duration and stopped with a local "
                    "save request. The raw console transcript stays private until download."
                )
                capture.completed_at = datetime.now(UTC)
                db.add(
                    AuditEvent(
                        admin_id=admin.id,
                        profile_id=profile.id,
                        category="diagnostic_capture",
                        result="success",
                        safe_detail=(
                            f"Captured a {payload.duration_seconds}-second local Spark profile for "
                            f"{profile.name}; output was not uploaded"
                        ),
                    )
                )
                db.commit()
                return diagnostic_capture_payload(capture)
        except asyncio.CancelledError:
            if profiler_started:
                try:
                    await asyncio.shield(manager.command("spark profiler cancel"))
                except (InvalidTransition, ValueError):
                    pass
            capture.status = "failed"
            capture.detail = "The local Spark diagnostic capture was cancelled before completion."
            capture.completed_at = datetime.now(UTC)
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="diagnostic_capture",
                    result="failed",
                    safe_detail=f"Local Spark diagnostic capture was cancelled for {profile.name}",
                )
            )
            db.commit()
            raise
        except (DiagnosticCaptureError, InvalidTransition, ValueError) as exc:
            if profiler_started:
                try:
                    await manager.command("spark profiler cancel")
                except (InvalidTransition, ValueError):
                    pass
            capture.status = "failed"
            capture.detail = str(exc)
            capture.completed_at = datetime.now(UTC)
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="diagnostic_capture",
                    result="failed",
                    safe_detail=f"Local Spark diagnostic capture failed for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        finally:
            diagnostic_capture_profiles.discard(profile.id)

    @app.get("/api/v1/profiles/{profile_id}/world-care")
    def profile_world_care(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        """Return read-only world, backup, destination, and recovery evidence."""

        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        properties = read_properties(directory)
        roots = backup_world_roots(directory)
        world_entries = [{"name": root.name, "size_bytes": tree_size(root)} for root in roots]
        world_bytes = strict_world_size(directory, properties)
        try:
            server_disk = disk_payload(directory)
        except OSError:
            server_disk = disk_payload(config.server_root)

        primary_backup = backup_directory(config.data_dir, profile.id)
        backup_size = tree_size(primary_backup)
        latest_checks: dict[str, BackupDestinationCheck] = {}
        for check in db.scalars(
            select(BackupDestinationCheck)
            .where(BackupDestinationCheck.profile_id == profile.id)
            .order_by(BackupDestinationCheck.checked_at.desc())
        ):
            latest_checks.setdefault(check.destination_path, check)
        destinations: list[dict[str, object]] = [
            {
                "label": "Blockstead local backup storage",
                "configured_path": str(primary_backup),
                "stored_bytes": backup_size,
                "disk": disk_payload(primary_backup),
                "last_check": (
                    destination_check_payload(latest_checks[str(primary_backup)])
                    if str(primary_backup) in latest_checks
                    else None
                ),
            }
        ]
        for raw in configured_backup_destinations(profile):
            destination = Path(raw) / "blockstead-backups" / profile.id
            destinations.append(
                {
                    "label": "Approved backup destination",
                    "configured_path": raw,
                    "stored_bytes": tree_size(destination),
                    "disk": disk_payload(destination),
                    "last_check": (
                        destination_check_payload(latest_checks[raw])
                        if raw in latest_checks
                        else None
                    ),
                }
            )

        recovery = recovery_snapshot_entries(directory, config.data_dir, profile.id)
        backups = db.scalars(
            select(BackupRecord)
            .where(
                BackupRecord.profile_id == profile.id,
                BackupRecord.status == "completed",
            )
            .order_by(BackupRecord.created_at.desc())
        ).all()
        latest = backups[0] if backups else None
        return {
            "worlds": world_entries,
            "world_size_bytes": world_bytes,
            "disk": server_disk,
            "last_verified_backup": backup_payload(latest) if latest else None,
            "backup_destinations": destinations,
            "recovery": {
                "entries": recovery,
                "total_bytes": sum(
                    size
                    for entry in recovery
                    if isinstance((size := entry.get("size_bytes")), int)
                ),
            },
            "cleanup": {
                "available": True,
                "detail": (
                    "Build a reviewed cleanup plan to inspect exact stale private artifacts. "
                    "Worlds, completed backups, and recovery copies are never included."
                ),
            },
        }

    @app.get("/api/v1/maintenance/changes")
    def maintenance_changes(request: Request, db: Db) -> dict[str, object]:
        """Return the versioned catalog of reviewable maintenance changes."""

        current(request, db)
        return maintenance_catalog().model_dump()

    def verify_protection_point(
        profile_id: str,
        backup_id: str,
        created_at: datetime,
        file_name: str,
        manifest_name: str,
        expected_sha256: str | None,
        size_bytes: int | None,
    ) -> BackupPoint:
        """Re-verify a backup archive instead of trusting its database record.

        Runs off the event loop because it hashes the archive, so it is handed
        plain values rather than the request's ORM objects or session.
        """

        try:
            verify_backup_archive(
                config.data_dir,
                profile_id,
                file_name,
                manifest_name,
                expected_sha256,
            )
        except (RestoreError, OSError) as exc:
            return BackupPoint(
                id=backup_id,
                created_at=created_at,
                verified=False,
                problem=str(exc),
                size_bytes=size_bytes,
            )
        return BackupPoint(
            id=backup_id, created_at=created_at, verified=True, size_bytes=size_bytes
        )

    # Categories whose saved change only reaches Minecraft on the next start.
    RESTART_PENDING_CATEGORIES = frozenset(
        {
            "settings_update",
            "settings_raw_update",
            "mod_config_update",
            "extension_install",
            "extension_update",
            "extension_toggle",
            "extension_remove",
            "extension_upload",
            "shared_map_profile",
        }
    )

    def pending_restart_for(profile: Profile, db: Session) -> tuple[bool, str]:
        """Whether a saved change is waiting for this running server's next start."""

        started_at = manager.started_at
        if started_at is None or app.state.active_profile_id != profile.id:
            return False, "The server is stopped, so nothing is waiting for a restart."
        recent = db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.profile_id == profile.id,
                AuditEvent.category.in_(RESTART_PENDING_CATEGORIES),
                AuditEvent.result.in_(("success", "accepted")),
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(20)
        ).all()
        # Compare in Python: SQLite stores these timestamps without an offset,
        # so a timezone-aware bound cannot be compared reliably in SQL.
        event = next(
            (
                candidate
                for candidate in recent
                if (
                    candidate.created_at.replace(tzinfo=timezone.utc)  # noqa: UP017
                    if candidate.created_at.tzinfo is None
                    else candidate.created_at
                )
                > started_at
            ),
            None,
        )
        if event is None:
            return False, "No saved change is waiting for a restart on this running server."
        return True, (
            f"A change saved after this server started is still waiting for a restart: "
            f"{event.safe_detail}"
        )

    async def upgrade_review_for(profile: Profile) -> UpgradeReview:
        """Read the published release list for one profile's distribution.

        A source that fails is passed through as a failure; it never becomes an
        empty list, which would read as "no newer release exists".
        """

        published: tuple[str, ...] | None = None
        problem: str | None = None
        if not profile.is_fixture:
            try:
                published = tuple(await list_versions(http_client, profile.distribution))
            except ProvisionError as exc:
                problem = str(exc)
        java_majors = frozenset(
            runtime.major for runtime in ([] if profile.is_fixture else discover_java_runtimes())
        )
        return review_upgrades(
            UpgradeContext(
                distribution=profile.distribution,
                current_version=profile.minecraft_version,
                is_fixture=profile.is_fixture,
                published=published,
                source_problem=problem,
                java_majors=java_majors,
            )
        )

    @app.get("/api/v1/profiles/{profile_id}/maintenance/upgrades")
    async def maintenance_upgrades(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        """Report published server releases and whether Blockstead can install one."""

        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        return (await upgrade_review_for(profile)).model_dump()

    @app.post("/api/v1/profiles/{profile_id}/maintenance/upgrades/apply")
    async def apply_server_upgrade(
        profile_id: str,
        payload: ServerUpgradeRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Apply one reviewed direct-artifact upgrade to a stopped server."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        require_server_stopped()
        fresh = await build_maintenance_plan(
            profile, MaintenanceRequest(change_id="server_upgrade"), db
        )
        if fresh.plan_id != payload.plan_id:
            raise HTTPException(
                409,
                "This server or its published upgrade target changed since the review. "
                "Run the preflight again before applying an upgrade.",
            )
        if fresh.readiness in {"blocked", "not_applicable"}:
            raise HTTPException(409, fresh.detail)
        if (
            not fresh.protection.verified
            or fresh.protection.age_hours is None
            or fresh.protection.age_hours > FRESH_PROTECTION_HOURS
        ):
            raise HTTPException(
                409,
                "Create a fresh verified backup, then run the upgrade preflight again.",
            )
        upgrade_review = await upgrade_review_for(profile)
        newest = upgrade_review.candidates[0] if upgrade_review.candidates else None
        if (
            newest is None
            or not newest.installable
            or newest.minecraft_version != payload.minecraft_version
        ):
            raise HTTPException(
                409,
                "That release is no longer the reviewed installable upgrade. "
                "Read the current release list and run the preflight again.",
            )

        directory = profile_directory(profile.id, db)
        staging: Path | None = None
        recovery_id: str | None = None
        try:
            async with update_lock:
                if update_install_in_progress():
                    raise HTTPException(
                        409,
                        "Blockstead itself is being updated. Upgrade the Minecraft server "
                        "after that finishes.",
                    )
                if profile.id in restoring_profiles:
                    raise HTTPException(
                        409, "A restore is in progress for this server. Wait for it to finish."
                    )
                pending_backup = db.scalar(
                    select(BackupRecord).where(
                        BackupRecord.profile_id == profile.id,
                        BackupRecord.status == "in_progress",
                    )
                )
                if pending_backup is not None:
                    raise HTTPException(
                        409, "A backup is still in progress. Wait for it to finish."
                    )
                active = active_launch_file(profile.distribution, directory)
                plan = await resolve_plan(
                    http_client, profile.distribution, payload.minecraft_version
                )
                if profile.distribution in {"vanilla", "paper"} and (
                    not plan.checksum_algorithm or not plan.checksum
                ):
                    raise HTTPException(
                        409,
                        "The official release did not provide the checksum Blockstead "
                        "requires for an automatic server upgrade.",
                    )
                staging = create_upgrade_staging(directory)
                await download_verified_file(
                    http_client,
                    plan.url,
                    staging,
                    active.name,
                    plan.checksum_algorithm,
                    plan.checksum,
                )
                recovery = promote_launch_upgrade(
                    server_directory=directory,
                    distribution=profile.distribution,
                    staged_file=staging / active.name,
                    recovery_root=config.data_dir,
                    profile_id=profile.id,
                    previous_version=profile.minecraft_version,
                    new_version=plan.minecraft_version,
                    previous_loader_version=profile.loader_version,
                    new_loader_version=plan.loader_version,
                )
                recovery_id = recovery.recovery_id
                profile.minecraft_version = plan.minecraft_version
                if plan.loader_version is not None:
                    profile.loader_version = plan.loader_version
                db.add(
                    AuditEvent(
                        admin_id=admin.id,
                        profile_id=profile.id,
                        category="server_upgrade",
                        result="success",
                        safe_detail=(
                            f"Upgraded {profile.name} to {plan.minecraft_version}; "
                            f"preserved launch recovery {recovery.recovery_id}; "
                            "world data was not rolled back"
                        ),
                    )
                )
                db.commit()
        except ProvisionError as exc:
            db.rollback()
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="server_upgrade",
                    result="failed",
                    safe_detail=f"Server upgrade failed before activation: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        except UpgradeOperationError as exc:
            db.rollback()
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="server_upgrade",
                    result="failed",
                    safe_detail=f"Server upgrade was not activated: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        except SQLAlchemyError as exc:
            db.rollback()
            recovery_problem: str | None = None
            if recovery_id is not None:
                try:
                    rollback_launch_upgrade(
                        server_directory=directory,
                        recovery_root=config.data_dir,
                        profile_id=profile_id,
                        recovery_id=recovery_id,
                        distribution=profile.distribution,
                    )
                except UpgradeOperationError as recovery_exc:
                    recovery_problem = str(recovery_exc)
            if recovery_problem:
                raise HTTPException(
                    500,
                    "The launch file changed, but Blockstead could not save the new "
                    "profile version or restore the prior launch file. Leave the server "
                    f"stopped and inspect its recovery record: {recovery_problem}",
                ) from exc
            raise HTTPException(
                500,
                "Blockstead could not save the upgraded profile, so the prior launch "
                "file was restored.",
            ) from exc
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

        assert recovery_id is not None
        return {
            "minecraft_version": profile.minecraft_version,
            "loader_version": profile.loader_version,
            "recovery_id": recovery_id,
            "restart_required": True,
            "detail": (
                f"{profile.name} now uses {profile.minecraft_version}. The previous "
                "launch file is preserved for an explicit rollback. Start the server "
                "when ready and check its console; Blockstead never rolls a world back "
                "automatically."
            ),
        }

    @app.post("/api/v1/profiles/{profile_id}/maintenance/upgrades/recovery/{recovery_id}")
    def rollback_server_upgrade(
        profile_id: str,
        recovery_id: str,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Explicitly restore a preserved launch file, never the world."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        require_server_stopped()
        try:
            recovered = rollback_launch_upgrade(
                server_directory=profile_directory(profile.id, db),
                recovery_root=config.data_dir,
                profile_id=profile.id,
                recovery_id=recovery_id,
                distribution=profile.distribution,
            )
        except UpgradeOperationError as exc:
            raise HTTPException(409, str(exc)) from exc
        previous_version = recovered.get("previous_version")
        previous_loader = recovered.get("previous_loader_version")
        profile.minecraft_version = previous_version if isinstance(previous_version, str) else None
        profile.loader_version = previous_loader if isinstance(previous_loader, str) else None
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="server_upgrade",
                result="recovered",
                safe_detail=(
                    f"Restored the prior launch file for {profile.name} from "
                    f"recovery {recovery_id}; world data was not changed"
                ),
            )
        )
        db.commit()
        return {
            "minecraft_version": profile.minecraft_version,
            "loader_version": profile.loader_version,
            "restart_required": True,
            "detail": (
                "The previous launch file was restored. The world was not rolled back; "
                "review the distribution's downgrade guidance before starting."
            ),
        }

    async def build_maintenance_plan(
        profile: Profile, payload: MaintenanceRequest, db: Session
    ) -> MaintenancePlan:
        """Gather current evidence and review one change against it.

        Scheduling re-runs this rather than trusting a plan the browser sends
        back, so a plan whose evidence has moved on cannot be acted on.
        """

        profile_id = profile.id
        directory = profile_directory(profile_id, db)
        properties = read_properties(directory)

        active = app.state.active_profile_id == profile.id
        snapshot = manager.snapshot()
        raw_state = str(snapshot["state"])
        if raw_state.startswith("ProcessState."):
            raw_state = raw_state.removeprefix("ProcessState.")
        state = raw_state if active else "STOPPED"
        occupant: str | None = None
        if not active and raw_state in {"STARTING", "RUNNING", "STOPPING", "DEGRADED"}:
            holder_id = snapshot["profile_id"]
            holder = db.get(Profile, str(holder_id)) if holder_id else None
            occupant = holder.name if holder else "Another server"

        status_probe = (
            await minecraft_status_probe(properties)
            if active and state in {"RUNNING", "DEGRADED"}
            else None
        )
        if status_probe is not None:
            remember_status_probe(profile.id, cast(dict[str, object], status_probe))
        status = status_probe["status"] if status_probe is not None else None
        configured_max = 20
        try:
            possible_max = int(properties.get("max-players", "20"))
            if 1 <= possible_max <= 1000:
                configured_max = possible_max
        except ValueError:
            pass
        online: int | None = None
        if status is not None:
            reported = status.get("online")
            if isinstance(reported, int):
                online = reported

        newest_backup = db.scalar(
            select(BackupRecord)
            .where(BackupRecord.profile_id == profile.id, BackupRecord.status == "completed")
            .order_by(BackupRecord.created_at.desc())
            .limit(1)
        )
        backup: BackupPoint | None = None
        if newest_backup is not None:
            backup_at = newest_backup.created_at
            if backup_at.tzinfo is None:
                backup_at = backup_at.replace(tzinfo=timezone.utc)  # noqa: UP017
            if newest_backup.file_name and newest_backup.manifest_name:
                backup = await asyncio.to_thread(
                    verify_protection_point,
                    profile.id,
                    newest_backup.id,
                    backup_at,
                    newest_backup.file_name,
                    newest_backup.manifest_name,
                    newest_backup.sha256,
                    newest_backup.size_bytes,
                )
            else:
                backup = BackupPoint(
                    id=newest_backup.id,
                    created_at=backup_at,
                    verified=False,
                    problem="This backup has no stored manifest, so it cannot be verified.",
                    size_bytes=newest_backup.size_bytes,
                )
        disk = psutil.disk_usage(str(config.data_dir))

        extensions_view = read_extensions(directory, profile.distribution)
        signature = tuple(
            sorted(
                f"{entry.file_name}@{entry.version or 'unknown'}"
                for entry in extensions_view.entries
            )
        )
        warnings = tuple(warning.message for warning in extensions_view.warnings)

        required = None if profile.is_fixture else required_java_major(profile.minecraft_version)
        compatible_java: bool | None = None
        launch_problem: str | None = None
        if not profile.is_fixture:
            runtimes = discover_java_runtimes()
            compatible_java = find_java(required, runtimes) is not None if required else None
            if profile.distribution == "unknown":
                launch_problem = "Blockstead did not recognize this server folder's distribution."
            else:
                try:
                    launch_arguments(profile.distribution, directory)
                except LaunchPlanError as exc:
                    launch_problem = str(exc)

        schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile.id))
        pending_events = db.scalars(
            select(AutomationEvent).where(
                AutomationEvent.profile_id == profile.id,
                AutomationEvent.completed_at.is_(None),
            )
        ).all()
        now_local = datetime.now().astimezone()
        upcoming = next_executions(schedule, pending_events, now_local, limit=1)
        next_label: str | None = None
        next_at: datetime | None = None
        if upcoming:
            next_label = str(upcoming[0]["label"])
            try:
                next_at = datetime.fromisoformat(str(upcoming[0]["at"]))
            except ValueError:
                next_at = None

        restart_pending, restart_detail = pending_restart_for(profile, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        # Only the upgrade review needs a published release list, so only it pays
        # for the lookup — the other reviews stay offline and fast.
        upgrade = (
            await upgrade_review_for(profile) if payload.change_id == "server_upgrade" else None
        )
        # The newest published release, installable or not: naming it lets the
        # review explain why it cannot be installed instead of going quiet.
        newest = upgrade.candidates[0] if upgrade and upgrade.candidates else None
        plan = assess_maintenance(
            MaintenanceContext(
                profile_id=profile.id,
                profile_name=profile.name,
                distribution=profile.distribution,
                distribution_label=info.label,
                minecraft_version=profile.minecraft_version,
                is_fixture=profile.is_fixture,
                state=state,
                selected_server_active=active,
                state_reason=str(snapshot["reason"]) if active else "This server is stopped.",
                online_players=online,
                max_players=configured_max,
                last_backup=backup,
                disk_free_bytes=int(disk.free),
                disk_total_bytes=int(disk.total),
                world_size_bytes=strict_world_size(directory, properties),
                extension_signature=signature,
                extension_warnings=warnings,
                required_java_major=required,
                compatible_java_found=compatible_java,
                launch_problem=launch_problem,
                pending_restart=restart_pending,
                pending_restart_detail=restart_detail,
                next_operation_label=next_label,
                next_operation_at=next_at,
                occupied_by=occupant,
                now=now_local,
                upgrade_source_available=upgrade is not None and upgrade.source == "available",
                upgrade_source_detail=upgrade.source_detail if upgrade else "",
                upgrade_up_to_date=upgrade.up_to_date if upgrade else None,
                upgrade_target=newest.minecraft_version if newest else None,
                upgrade_installable=bool(newest and newest.installable),
                upgrade_distribution_supported=bool(upgrade and upgrade.installable_here),
                upgrade_detail=(
                    newest.detail if newest else (upgrade.install_detail if upgrade else "")
                ),
            ),
            payload,
        )
        return plan

    @app.post("/api/v1/profiles/{profile_id}/maintenance/preflight")
    async def maintenance_preflight(
        profile_id: str,
        payload: MaintenanceRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Review one maintenance change against current evidence. Changes nothing."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        plan = await build_maintenance_plan(profile, payload, db)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="maintenance_preflight",
                result="reviewed",
                safe_detail=maintenance_audit_detail(plan, profile.name),
            )
        )
        db.commit()
        return plan.model_dump()

    # response_model=None: a stale plan answers 409 with the fresh review attached,
    # so this route returns either a body or a prepared response.
    @app.post(
        "/api/v1/profiles/{profile_id}/maintenance/schedule",
        status_code=201,
        response_model=None,
    )
    async def schedule_reviewed_plan(
        profile_id: str,
        payload: MaintenanceScheduleRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object] | JSONResponse:
        """Book a one-time maintenance window for a plan the owner just reviewed.

        The plan is re-reviewed here. A stale plan is refused with the fresh
        review attached, so a schedule can never be built on evidence that has
        since changed.
        """

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        run_at_dt = datetime.strptime(payload.run_at, "%Y-%m-%dT%H:%M")
        if run_at_dt <= datetime.now().replace(second=0, microsecond=0):
            raise HTTPException(422, "Choose a maintenance time in the future.")

        fresh = await build_maintenance_plan(
            profile, MaintenanceRequest(change_id=payload.change_id), db
        )
        if fresh.plan_id != payload.plan_id:
            db.add(
                AuditEvent(
                    admin_id=admin.id,
                    profile_id=profile.id,
                    category="maintenance_schedule",
                    result="refused",
                    safe_detail=(
                        f"Refused to schedule a stale plan for {profile.name}: reviewed "
                        f"{payload.plan_id}, current evidence is {fresh.plan_id}"
                    ),
                )
            )
            db.commit()
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "stale_plan",
                        "message": (
                            "This server has changed since you reviewed that plan, so "
                            "Blockstead did not schedule it. Review the current plan below."
                        ),
                    },
                    "plan": fresh.model_dump(),
                },
            )
        if fresh.readiness == "blocked":
            raise HTTPException(
                409, "This plan is blocked right now, so Blockstead will not schedule it."
            )
        if fresh.readiness == "not_applicable":
            raise HTTPException(409, "There is nothing to change, so there is nothing to schedule.")

        pending_count = db.scalar(
            select(func.count())
            .select_from(AutomationEvent)
            .where(
                AutomationEvent.profile_id == profile_id,
                AutomationEvent.completed_at.is_(None),
            )
        )
        if pending_count is not None and pending_count >= 20:
            raise HTTPException(409, "This server already has 20 pending maintenance events.")
        if db.scalar(select(Schedule).where(Schedule.profile_id == profile_id)) is None:
            db.add(Schedule(profile_id=profile_id, enabled=False))
        # The reviewed plan always carries a protection step, so the booked
        # window always backs up before it stops; that is not an owner toggle.
        event = AutomationEvent(
            profile_id=profile_id,
            run_at=payload.run_at,
            backup_before_stop=True,
            power_off_after_stop=False,
            only_when_empty=payload.only_when_empty,
        )
        db.add(event)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="maintenance_schedule",
                result="success",
                safe_detail=(
                    f"Scheduled “{fresh.change.title}” on {profile.name} for "
                    f"{payload.run_at} from reviewed plan {fresh.plan_id}"
                ),
            )
        )
        db.commit()
        return {
            "id": event.id,
            "profile_id": profile_id,
            "run_at": payload.run_at,
            "plan_id": fresh.plan_id,
            "change_id": payload.change_id,
            "only_when_empty": payload.only_when_empty,
            "backup_before_stop": True,
            "detail": (
                f"Blockstead will stop {profile.name} at {payload.run_at} after a "
                "verified backup. Applying the change itself is still yours to do."
            ),
        }

    @app.get("/api/v1/troubleshooting/problems")
    def troubleshooting_problems(request: Request, db: Db) -> dict[str, object]:
        """Return the versioned, non-executable troubleshooting catalog."""

        current(request, db)
        return troubleshooting_catalog().model_dump()

    @app.post("/api/v1/profiles/{profile_id}/troubleshooting/assess")
    async def troubleshoot_profile(
        profile_id: str,
        payload: TroubleshootingRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Run bounded read-only checks for one selected troubleshooting playbook."""

        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        properties = read_properties(directory)
        active = app.state.active_profile_id == profile.id
        snapshot = manager.snapshot()
        state = str(snapshot["state"]) if active else "STOPPED"
        if state.startswith("ProcessState."):
            state = state.removeprefix("ProcessState.")
        status_probe = (
            await minecraft_status_probe(properties)
            if active and state in {"RUNNING", "DEGRADED"}
            else None
        )
        if status_probe is not None:
            remember_status_probe(profile.id, cast(dict[str, object], status_probe))
        status = status_probe["status"] if status_probe is not None else None
        public_ip = (
            await app.state.public_ip_discovery.discover()
            if payload.problem_id == "public_connection"
            else {
                "available": False,
                "ip": None,
                "detail": "Public-IP discovery was not needed for this playbook.",
            }
        )
        join = join_details(properties, public_ip)

        required: int | None = None
        compatible_java: bool | None = True
        eula: bool | None = None
        launch_problem: str | None = None
        if not profile.is_fixture and payload.problem_id == "server_wont_start":
            required = required_java_major(profile.minecraft_version)
            runtimes = discover_java_runtimes()
            compatible_java = (
                find_java(required, runtimes) is not None if required is not None else None
            )
            eula = eula_accepted(directory)
            if profile.distribution == "unknown":
                launch_problem = "The distribution of this server folder was not recognized."
            else:
                try:
                    launch_arguments(profile.distribution, directory)
                except LaunchPlanError as exc:
                    launch_problem = str(exc)

        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(config.data_dir))
        errors = [str(entry["message"]) for entry in reversed(diagnostics.tail(6, logging.WARNING))]
        assessment = assess_troubleshooting(
            payload,
            TroubleshootingContext(
                profile_id=profile.id,
                profile_name=profile.name,
                distribution=profile.distribution,
                minecraft_version=profile.minecraft_version,
                state=state,
                selected_server_active=active,
                state_reason=str(snapshot["reason"]) if active else "This server is stopped.",
                properties=properties,
                players=read_players(directory),
                local_status_responded=(status is not None)
                if active and state in {"RUNNING", "DEGRADED"}
                else None,
                local_status_outcome=(
                    str(status_probe["outcome"]) if status_probe is not None else None
                ),
                join=cast(dict[str, object], join),
                eula_accepted=eula,
                required_java_major=required,
                compatible_java_found=compatible_java,
                launch_problem=launch_problem,
                disk_percent=float(disk.percent),
                memory_percent=float(memory.percent),
                cpu_percent=float(psutil.cpu_percent(interval=None)),
                recent_errors=errors,
            ),
        )
        return assessment.model_dump()

    @app.post("/api/v1/profiles/{profile_id}/troubleshooting/repair")
    async def repair_troubleshooting_problem(
        profile_id: str,
        payload: TroubleshootingRepairRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        """Execute one registered repair after rechecking its applicability."""

        if payload.action_id == "enable_lan":
            return enable_profile_lan_connections(profile_id, request, db)

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        snapshot = manager.snapshot()
        state = str(snapshot["state"])
        if state.startswith("ProcessState."):
            state = state.removeprefix("ProcessState.")
        if app.state.active_profile_id != profile.id or state != "RUNNING":
            raise HTTPException(
                409,
                "This repair is only available while the selected server is running.",
            )
        assert payload.player_name is not None
        directory = profile_directory(profile_id, db)
        players = read_players(directory)
        normalized = payload.player_name.casefold()
        if payload.action_id == "allowlist_add":
            whitelist_enabled = (
                read_properties(directory).get("white-list", "false").strip().casefold() == "true"
            )
            if not whitelist_enabled:
                raise HTTPException(409, "The allowlist is no longer enabled for this server.")
            if not players.allowlist.readable:
                raise HTTPException(409, "The server allowlist could not be read safely.")
            if normalized in {entry.name.casefold() for entry in players.allowlist.players}:
                raise HTTPException(409, "That player is already on the allowlist.")
            player_request = PlayerActionRequest(action="whitelist_add", player=payload.player_name)
            detail = f"Requested allowlist access for {payload.player_name}"
        else:
            if not players.bans.readable:
                raise HTTPException(409, "The banned-player list could not be read safely.")
            if normalized not in {entry.name.casefold() for entry in players.bans.players}:
                raise HTTPException(409, "That player is no longer banned.")
            player_request = PlayerActionRequest(action="pardon", player=payload.player_name)
            detail = f"Requested pardon for {payload.player_name}"
        try:
            await manager.command(player_request.console_command)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="troubleshooting_repair",
                result="accepted",
                safe_detail=f"{detail} on {profile.name} through Server Troubleshooting",
            )
        )
        db.commit()
        return {
            "status": "accepted",
            "detail": (
                f"Minecraft accepted the repair command for {payload.player_name}. "
                "Blockstead will check the evidence again."
            ),
        }

    @app.post("/api/v1/profiles/{profile_id}/connection/refresh")
    async def refresh_profile_connection(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        """Retry the bounded public-IP lookup at the owner's request."""

        mutation(request, db)
        properties = read_properties(profile_directory(profile_id, db))
        public_ip = await app.state.public_ip_discovery.discover(force=True)
        return cast(dict[str, object], join_details(properties, public_ip))

    @app.post("/api/v1/profiles/{profile_id}/connection/enable-lan")
    def enable_profile_lan_connections(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        """Safely clear a loopback-only bind after an explicit owner request."""

        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        snapshot = manager.snapshot()
        if app.state.active_profile_id == profile.id and snapshot["state"] in {
            "RUNNING",
            "STARTING",
            "STOPPING",
            "DEGRADED",
        }:
            raise HTTPException(
                409,
                "Stop this Minecraft server before changing its network bind address.",
            )
        directory = profile_directory(profile_id, db)
        bind = read_properties(directory).get("server-ip", "").strip()
        if bind not in {"127.0.0.1", "::1", "localhost"}:
            raise HTTPException(
                409,
                "This repair is only available when server.properties uses a loopback address.",
            )
        view = read_settings(directory)
        if view.revision is None:
            raise HTTPException(409, "No editable server.properties file was found.")
        try:
            result = apply_settings_update(
                directory,
                config.data_dir,
                profile_id,
                view.revision,
                {"server-ip": ""},
            )
        except SettingsConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except SettingsValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                409,
                "Blockstead could not snapshot and safely replace server.properties.",
            ) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="connection_repair",
                result="success",
                safe_detail=(
                    "Cleared the loopback server bind for profile "
                    f"{profile_id}; recovery snapshot {result.snapshot_name}"
                ),
            )
        )
        db.commit()
        return {
            "detail": "Local-network listening is enabled. Restart Minecraft before testing it.",
            "snapshot_name": result.snapshot_name,
        }

    @app.get("/api/v1/system/metrics")
    def system_metrics(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(config.data_dir))
        process: dict[str, object] = {"uptime_seconds": None, "memory_bytes": None}
        pid = manager.snapshot()["pid"]
        if isinstance(pid, int):
            try:
                process["memory_bytes"] = psutil.Process(pid).memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            if manager.started_at is not None:
                now = datetime.now(timezone.utc)  # noqa: UP017
                process["uptime_seconds"] = max(0.0, (now - manager.started_at).total_seconds())
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory": {
                "total_bytes": memory.total,
                "used_bytes": memory.used,
                "percent": memory.percent,
            },
            "disk": {"total_bytes": disk.total, "used_bytes": disk.used, "percent": disk.percent},
            "process": process,
        }

    async def diagnostics_payload(
        db: Session, *, focus_event: AuditEvent | None = None
    ) -> dict[str, object]:
        public_ip = await app.state.public_ip_discovery.discover()
        snapshot = manager.snapshot()
        active_profile_id = app.state.active_profile_id
        state = str(snapshot["state"])
        if state.startswith("ProcessState."):
            state = state.removeprefix("ProcessState.")
        if isinstance(active_profile_id, str) and state in {"RUNNING", "DEGRADED"}:
            active_profile = db.get(Profile, active_profile_id)
            if active_profile is not None:
                try:
                    directory = canonical_child(
                        Path(active_profile.server_directory), config.server_root
                    )
                except (OSError, ValueError):
                    pass
                else:
                    probe = await minecraft_status_probe(read_properties(directory))
                    remember_status_probe(active_profile_id, cast(dict[str, object], probe))
        return build_report(
            config=config,
            buffer=diagnostics,
            server={**snapshot, "profile_id": active_profile_id},
            static_dir=resolve_static_dir(config.static_dir),
            db=db,
            focus_event=focus_event,
            public_ip=public_ip,
            status_probes=dict(app.state.minecraft_status_probes),
        )

    @app.get("/api/v1/activity")
    def activity_feed(
        request: Request,
        db: Db,
        profile_id: str | None = None,
        category: str | None = None,
        result: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        current(request, db)
        if limit < 1 or limit > 100 or offset < 0:
            raise HTTPException(422, "Activity pagination is outside the supported range.")
        if profile_id is not None and db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That server profile was not found.")
        return list_activity(
            db,
            profile_id=profile_id,
            group=category,
            result=result,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/v1/activity/{event_id}/report")
    async def activity_report(event_id: str, request: Request, db: Db) -> Response:
        current(request, db)
        event = db.get(AuditEvent, event_id)
        if event is None:
            raise HTTPException(404, "That activity event was not found.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
        report = await diagnostics_payload(db, focus_event=event)
        return Response(
            content=json.dumps(report, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="blockstead-event-{event.id[:8]}-{stamp}.json"'
                )
            },
        )

    @app.get("/api/v1/notification-preferences")
    def notification_preferences(request: Request, db: Db) -> dict[str, object]:
        admin, _ = current(request, db)
        row = preferences_for(db, admin.id, persist=False)
        return preferences_payload(row)

    @app.put("/api/v1/notification-preferences")
    def update_notification_preferences(
        payload: NotificationPreferencesRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        row = preferences_for(db, admin.id)
        for name, value in payload.model_dump().items():
            setattr(row, name, value)
        row.updated_at = datetime.now(timezone.utc)  # noqa: UP017
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="settings_change",
                result="success",
                safe_detail="Updated local notification preferences",
            )
        )
        db.commit()
        return preferences_payload(row)

    @app.get("/api/v1/notifications")
    def local_notifications(request: Request, db: Db) -> dict[str, object]:
        admin, _ = current(request, db)
        prefs = preferences_for(db, admin.id, persist=False)
        alerts: list[dict[str, object]] = []
        seen = prefs.last_seen_at

        def after_seen(value: datetime) -> bool:
            candidate = value
            marker = seen
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)  # noqa: UP017
            if marker is not None and marker.tzinfo is None:
                marker = marker.replace(tzinfo=timezone.utc)  # noqa: UP017
            return marker is None or candidate > marker

        profiles = list(db.scalars(select(Profile)).all())
        root = config.server_root.resolve(strict=False)
        resolved_profiles: dict[str, Path] = {}
        for profile in profiles:
            try:
                resolved_profiles[profile.id] = Path(profile.server_directory).resolve(strict=False)
            except OSError:
                continue
        for profile in profiles:
            directory = resolved_profiles.get(profile.id)
            if directory is None:
                unsafe_detail = "Its server folder could not be resolved safely."
            elif directory == root:
                unsafe_detail = (
                    "It points at the entire server root. Remove only this Blockstead record "
                    "and keep the files."
                )
            elif root not in directory.parents:
                unsafe_detail = "Its server folder is outside the configured server root."
            elif any(
                other_id != profile.id and other != root and directory_overlap(directory, other)
                for other_id, other in resolved_profiles.items()
            ):
                unsafe_detail = (
                    "Its folder overlaps another managed server. Keep files when removing the "
                    "duplicate or parent profile record."
                )
            else:
                continue
            alerts.append(
                {
                    "id": f"unsafe-profile-directory-{profile.id}",
                    "kind": "unsafe_profile_directory",
                    "title": f"{profile.name} has an unsafe profile folder",
                    "detail": unsafe_detail,
                    "severity": "danger",
                    "created_at": profile.created_at.isoformat(),
                    "recovery_to": "/servers",
                }
            )

        failed_backups = db.scalars(
            select(BackupRecord)
            .where(BackupRecord.status == "failed")
            .order_by(BackupRecord.created_at.desc())
            .limit(10)
        ).all()
        if prefs.failed_backups:
            for record in failed_backups:
                occurred_at = record.completed_at or record.created_at
                if after_seen(occurred_at):
                    failed_profile = db.get(Profile, record.profile_id)
                    alerts.append(
                        {
                            "id": f"failed-backup-{record.id}",
                            "kind": "failed_backup",
                            "title": "A world backup failed",
                            "detail": record.result,
                            "severity": "danger",
                            "created_at": occurred_at.isoformat(),
                            "recovery_to": (
                                f"/servers/{record.profile_id}/backups"
                                if failed_profile is not None
                                else "/servers"
                            ),
                        }
                    )

        if prefs.failed_automations:
            failed_runs = db.scalars(
                select(AutomationRun)
                .where(AutomationRun.status == "failed")
                .order_by(AutomationRun.started_at.desc())
                .limit(10)
            ).all()
            for run in failed_runs:
                if not after_seen(run.started_at):
                    continue
                automation_profile = db.get(Profile, run.profile_id)
                alerts.append(
                    {
                        "id": f"failed-automation-{run.id}",
                        "kind": "failed_automation",
                        "title": "A server automation failed",
                        "detail": run.detail,
                        "severity": "danger",
                        "created_at": run.started_at.isoformat(),
                        "recovery_to": (
                            f"/servers/{run.profile_id}/schedule"
                            if automation_profile is not None
                            else "/servers"
                        ),
                    }
                )

        snapshot = manager.snapshot()
        if (
            prefs.server_crashes
            and snapshot["state"] == "CRASHED"
            and after_seen(manager.state_changed_at)
        ):
            profile_id = app.state.active_profile_id
            alerts.append(
                {
                    "id": "current-server-crash",
                    "kind": "server_crash",
                    "title": "The Minecraft server crashed",
                    "detail": snapshot["reason"],
                    "severity": "danger",
                    "created_at": (manager.state_changed_at.isoformat()),
                    "recovery_to": recovery_path("server_crash", profile_id),
                }
            )

        disk = psutil.disk_usage(str(config.data_dir))
        if prefs.low_disk_space and disk.percent >= 90:
            alerts.append(
                {
                    "id": "low-disk-space",
                    "kind": "low_disk_space",
                    "title": "Disk space is running low",
                    "detail": f"The Blockstead data disk is {disk.percent:.0f}% full.",
                    "severity": "danger" if disk.percent >= 95 else "warning",
                    "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
                    "recovery_to": "/system",
                }
            )

        update = update_status().get("last_result")
        if (
            prefs.completed_updates
            and isinstance(update, dict)
            and update.get("state") == "succeeded"
        ):
            update_at = datetime.fromisoformat(str(update["at"]).replace("Z", "+00:00"))
            if after_seen(update_at):
                alerts.append(
                    {
                        "id": f"completed-update-{update.get('commit') or update['at']}",
                        "kind": "completed_update",
                        "title": "Blockstead finished updating",
                        "detail": str(update.get("detail") or "The update completed successfully."),
                        "severity": "success",
                        "created_at": update_at.isoformat(),
                        "recovery_to": "/system",
                    }
                )
        alerts.sort(key=lambda item: str(item["created_at"]), reverse=True)
        return {"alerts": alerts, "unread_count": len(alerts)}

    @app.post("/api/v1/notifications/acknowledge", status_code=204)
    def acknowledge_notifications(request: Request, db: Db) -> None:
        admin = mutation(request, db)
        row = preferences_for(db, admin.id)
        row.last_seen_at = datetime.now(timezone.utc)  # noqa: UP017
        row.updated_at = row.last_seen_at
        db.commit()

    @app.get("/api/v1/system/diagnostics")
    async def system_diagnostics(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return await diagnostics_payload(db)

    @app.get("/api/v1/system/diagnostics/report")
    async def system_diagnostics_report(request: Request, db: Db) -> Response:
        current(request, db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
        return Response(
            content=json.dumps(await diagnostics_payload(db), indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="blockstead-report-{stamp}.json"'
            },
        )

    @app.get("/api/v1/updates/status")
    def updates_status(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return update_status()

    @app.post("/api/v1/updates/check")
    async def updates_check(request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        return await check_for_update()

    @app.post("/api/v1/updates/install")
    async def updates_install(request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        async with update_lock:
            if not updates.update_capable():
                raise HTTPException(
                    409,
                    "This copy of Blockstead cannot update itself. "
                    "Install it with scripts/install-linux.sh to enable updates.",
                )
            if update_install_in_progress():
                raise HTTPException(409, "A Blockstead update is already in progress.")
            if critical_update_operation_in_progress():
                raise HTTPException(
                    409,
                    "Wait for the current backup or restore to finish before updating.",
                )
            latest = app.state.latest_commit
            if latest is None:
                raise HTTPException(409, "Blockstead has not checked for an update yet.")
            state = updates.read_state(config.data_dir)
            if not updates.is_behind(
                installed_build,
                latest,
                baseline=state.baseline_commit,
            ):
                raise HTTPException(409, "Blockstead is already up to date.")
            if manager.snapshot()["state"] in {
                "RUNNING",
                "STARTING",
                "STOPPING",
                "DEGRADED",
            }:
                raise HTTPException(
                    409,
                    "Stop the Minecraft server before updating, so players are not "
                    "disconnected partway through.",
                )
            # This endpoint is an administrator's explicit retry. It is allowed
            # to re-request a commit that automatic checks suppressed after a
            # non-retryable failure.
            queue_update(
                latest,
                state,
                resume_profile_id=(
                    state.resume_profile_id if state.resume_commit == latest.commit else None
                ),
            )
            app.state.update_decision = updates.Decision.INSTALL
            return update_status()

    @app.post("/api/v1/updates/acknowledge")
    async def updates_acknowledge(request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        async with update_lock:
            updates.acknowledge(config.data_dir, installed_build)
            return update_status()

    @app.get("/api/v1/server/state")
    def process_state(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return {**manager.snapshot(), "profile_id": app.state.active_profile_id}

    def eula_accepted(directory: Path) -> bool:
        eula = directory / "eula.txt"
        try:
            if not eula.is_file():
                return False
            with eula.open(encoding="utf-8", errors="replace") as handle:
                return "eula=true" in handle.read(4096).lower()
        except OSError:
            return False

    def launch_spec(profile: Profile, mode: str) -> tuple[tuple[str, ...], Path, str]:
        try:
            directory = canonical_child(Path(profile.server_directory), config.server_root)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "The profile folder is no longer inside the allowed server root."
            ) from exc
        if profile.is_fixture:
            return (
                (sys.executable, str(Path(__file__).with_name("fake_server.py")), "--mode", mode),
                directory,
                "Fixture",
            )
        info = DISTRIBUTIONS.get(profile.distribution)
        if info is None or profile.distribution == "unknown":
            raise HTTPException(
                409, "Blockstead cannot launch this profile because its distribution is unknown."
            )
        if not eula_accepted(directory):
            raise HTTPException(
                409, "Accept the Minecraft EULA in eula.txt before starting this server."
            )
        required = required_java_major(profile.minecraft_version)
        runtime = find_java(required, discover_java_runtimes())
        if runtime is None:
            needed = f"Java {required} or newer" if required else "a Java runtime"
            raise HTTPException(
                409,
                f"Starting this server needs {needed}, but none was found on this computer. "
                "Install it and try again.",
            )
        try:
            arguments = launch_arguments(profile.distribution, directory, runtime.path)
        except LaunchPlanError as exc:
            raise HTTPException(409, str(exc)) from exc
        return arguments, directory, info.label

    @app.get("/api/v1/server/logs")
    def process_logs(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        return [event.__dict__ for event in manager.logs()]

    @app.get("/api/v1/automation/capabilities")
    def automation_capabilities(request: Request, db: Db) -> dict[str, bool]:
        current(request, db)
        return {"host_power": scheduler.power_capable}

    @app.get("/api/v1/schedules")
    def list_schedules(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)

        def event_payload(event: AutomationEvent) -> dict[str, object]:
            return {
                "id": event.id,
                "run_at": event.run_at,
                "backup_before_stop": event.backup_before_stop,
                "power_off_after_stop": event.power_off_after_stop,
                "wake_time": event.wake_time,
                "only_when_empty": event.only_when_empty,
            }

        def run_payload(run: AutomationRun) -> dict[str, object]:
            return {
                "id": run.id,
                "trigger": run.trigger,
                "action": run.action,
                "status": run.status,
                "steps": json.loads(run.steps),
                "detail": run.detail,
                "duration_ms": run.duration_ms,
                "started_at": run.started_at.isoformat(),
                "completed_at": run.completed_at.isoformat(),
            }

        now = datetime.now().astimezone()
        payloads: list[dict[str, object]] = []
        for schedule in db.scalars(select(Schedule)).all():
            events = db.scalars(
                select(AutomationEvent)
                .where(
                    AutomationEvent.profile_id == schedule.profile_id,
                    AutomationEvent.completed_at.is_(None),
                )
                .order_by(AutomationEvent.run_at)
            ).all()
            runs = db.scalars(
                select(AutomationRun)
                .where(AutomationRun.profile_id == schedule.profile_id)
                .order_by(AutomationRun.started_at.desc())
                .limit(20)
            ).all()
            payloads.append(
                {
                    "id": schedule.id,
                    "profile_id": schedule.profile_id,
                    "enabled": schedule.enabled,
                    "start_time": schedule.start_time,
                    "stop_time": schedule.stop_time,
                    "backup_before_stop": schedule.backup_before_stop,
                    "power_off_after_stop": schedule.power_off_after_stop,
                    "wake_time": schedule.wake_time,
                    "weekdays": parse_weekdays(schedule.weekdays),
                    "only_when_empty": schedule.only_when_empty,
                    "power_capable": scheduler.power_capable,
                    "maintenance_steps": automation_steps(
                        schedule.backup_before_stop, schedule.power_off_after_stop
                    ),
                    "next_executions": next_executions(schedule, events, now),
                    "one_time_events": [event_payload(event) for event in events],
                    "history": [run_payload(run) for run in runs],
                }
            )
        return payloads

    @app.put("/api/v1/schedules/{profile_id}")
    def save_schedule(
        profile_id: str, payload: ScheduleRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        if payload.profile_id != profile_id or db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        if payload.power_off_after_stop and not payload.stop_time:
            raise HTTPException(422, "A computer shutdown needs a server stop time.")
        if payload.power_off_after_stop and not scheduler.power_capable:
            raise HTTPException(
                422,
                "Linux host shutdown is unavailable because the installer power helper is missing.",
            )
        schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile_id))
        if schedule is None:
            schedule = Schedule(profile_id=profile_id)
            db.add(schedule)
        values = payload.model_dump(exclude={"weekdays"})
        values["weekdays"] = ",".join(str(day) for day in payload.weekdays)
        for name, value in values.items():
            setattr(schedule, name, value)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=payload.profile_id,
                category="schedule_update",
                result="success",
                safe_detail=f"Updated schedule for profile {profile_id}",
            )
        )
        db.commit()
        return {
            "id": schedule.id,
            **payload.model_dump(),
            "power_capable": scheduler.power_capable,
            "maintenance_steps": automation_steps(
                schedule.backup_before_stop, schedule.power_off_after_stop
            ),
            "next_executions": next_executions(schedule, [], datetime.now().astimezone()),
            "one_time_events": [],
            "history": [],
        }

    @app.post("/api/v1/profiles/{profile_id}/automation-events", status_code=201)
    def create_automation_event(
        profile_id: str,
        payload: AutomationEventRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        admin = mutation(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        run_at_dt = datetime.strptime(payload.run_at, "%Y-%m-%dT%H:%M")
        if run_at_dt <= datetime.now().replace(second=0, microsecond=0):
            raise HTTPException(422, "Choose a one-time maintenance time in the future.")
        if payload.power_off_after_stop and not scheduler.power_capable:
            raise HTTPException(
                422,
                "Linux host shutdown is unavailable because the installer power helper is missing.",
            )
        pending_count = db.scalar(
            select(func.count())
            .select_from(AutomationEvent)
            .where(
                AutomationEvent.profile_id == profile_id,
                AutomationEvent.completed_at.is_(None),
            )
        )
        if pending_count is not None and pending_count >= 20:
            raise HTTPException(409, "This server already has 20 pending maintenance events.")
        schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile_id))
        if schedule is None:
            db.add(Schedule(profile_id=profile_id, enabled=False))
        event = AutomationEvent(profile_id=profile_id, **payload.model_dump())
        db.add(event)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="automation_event",
                result="success",
                safe_detail=f"Scheduled one-time maintenance for {profile.name}",
            )
        )
        db.commit()
        return {"id": event.id, "profile_id": profile_id, **payload.model_dump()}

    @app.delete("/api/v1/profiles/{profile_id}/automation-events/{event_id}", status_code=204)
    def cancel_automation_event(profile_id: str, event_id: str, request: Request, db: Db) -> None:
        admin = mutation(request, db)
        event = db.get(AutomationEvent, event_id)
        if event is None or event.profile_id != profile_id or event.completed_at is not None:
            raise HTTPException(404, "That pending maintenance event was not found.")
        db.delete(event)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="automation_event",
                result="success",
                safe_detail=f"Cancelled one-time maintenance for profile {profile_id}",
            )
        )
        db.commit()

    @app.post("/api/v1/schedules/{profile_id}/run")
    async def run_automation(
        profile_id: str,
        payload: AutomationRunRequest,
        request: Request,
        db: Db,
    ) -> dict[str, object]:
        mutation(request, db)
        if db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        try:
            run = await scheduler.run_now(
                profile_id, payload.action, confirm_power=payload.confirm_power
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "id": run.id,
            "trigger": run.trigger,
            "action": run.action,
            "status": run.status,
            "steps": json.loads(run.steps),
            "detail": run.detail,
            "duration_ms": run.duration_ms,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat(),
        }

    @app.post("/api/v1/server/start", status_code=202)
    async def process_start(payload: StartRequest, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        async with update_lock:
            if update_install_in_progress():
                raise HTTPException(
                    409, "Blockstead is being updated. Start the server after it finishes."
                )
            profile = db.get(Profile, payload.profile_id)
            if profile is None:
                raise HTTPException(404, "That profile was not found.")
            if profile.id in restoring_profiles:
                raise HTTPException(
                    409, "A restore is in progress for this server. Wait for it to finish."
                )
            try:
                label = await start_profile(profile, payload.mode)
            except InvalidTransition as exc:
                raise HTTPException(409, str(exc)) from exc
        log.info("Starting the %s server for profile %s", label, profile.name)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="server_start",
                result="accepted",
                safe_detail=f"Started {profile.distribution} profile {profile.name}",
            )
        )
        db.commit()
        return {**manager.snapshot(), "profile_id": profile.id}

    @app.post("/api/v1/server/command", status_code=202)
    async def process_command(payload: CommandRequest, request: Request, db: Db) -> dict[str, str]:
        admin = mutation(request, db)
        try:
            await manager.command(payload.command)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=app.state.active_profile_id,
                category="console_command",
                result="accepted",
                safe_detail="Sent one Minecraft console command; content omitted",
            )
        )
        db.commit()
        return {"status": "accepted"}

    @app.get("/api/v1/profiles/{profile_id}/commands")
    def guided_commands(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile, view, origin_project_ids = command_provider_context(profile_id, db)
        # Presentation filtering is helpful, but the POST route repeats this
        # provider check so hidden commands cannot be invoked by hand.
        providers = active_provider_ids(
            profile.distribution,
            view.entries,
            profile.minecraft_version,
            origin_project_ids,
        )
        return catalog_payload(providers)

    @app.post("/api/v1/server/guided-command", status_code=202)
    async def guided_command(
        payload: GuidedCommandRequest, request: Request, db: Db
    ) -> dict[str, str]:
        admin = mutation(request, db)
        profile = db.get(Profile, payload.profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        if app.state.active_profile_id != payload.profile_id:
            raise HTTPException(409, "Start this profile before sending it a command.")
        _, view, origin_project_ids = command_provider_context(payload.profile_id, db)
        providers = active_provider_ids(
            profile.distribution,
            view.entries,
            profile.minecraft_version,
            origin_project_ids,
        )
        try:
            command, safety = render_guided_command(payload.command_id, payload.values, providers)
            if safety != "normal" and not payload.confirmed:
                raise ValueError("Review and confirm this command before sending it.")
            await manager.command(command)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=payload.profile_id,
                category="guided_command",
                result="accepted",
                safe_detail=f"Sent guided command {payload.command_id}; values omitted",
            )
        )
        db.commit()
        return {"status": "accepted", "command": command}

    @app.post("/api/v1/server/restart", status_code=202)
    async def process_restart(payload: StartRequest, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        async with update_lock:
            if update_install_in_progress():
                raise HTTPException(
                    409, "Blockstead is being updated. Restart the server after it finishes."
                )
            try:
                if app.state.active_profile_id != payload.profile_id:
                    raise InvalidTransition("Restart the profile that is currently running.")
                if not await manager.stop():
                    raise InvalidTransition(
                        "The server did not stop before the timeout. "
                        "Force stop it, then start it again."
                    )
                profile = db.get(Profile, payload.profile_id)
                if profile is None:
                    raise HTTPException(404, "That profile was not found.")
                label = await start_profile(profile, payload.mode)
            except InvalidTransition as exc:
                raise HTTPException(409, str(exc)) from exc
        log.info("Restarting the %s server for profile %s", label, profile.name)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile.id,
                category="server_restart",
                result="accepted",
                safe_detail=f"Restarted profile {profile.name}",
            )
        )
        db.commit()
        return manager.snapshot()

    @app.post("/api/v1/server/players", status_code=202)
    async def player_action(
        payload: PlayerActionRequest, request: Request, db: Db
    ) -> dict[str, str]:
        admin = mutation(request, db)
        try:
            await manager.command(payload.console_command)
        except (InvalidTransition, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=app.state.active_profile_id,
                category="player_action",
                result="accepted",
                safe_detail=f"Requested {payload.action} for {payload.player}",
            )
        )
        db.commit()
        return {"status": "accepted", "command": payload.console_command}

    @app.post("/api/v1/server/stop", status_code=202)
    async def process_stop(request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        backup_record: BackupRecord | None = None
        active_profile_id = app.state.active_profile_id
        if active_profile_id:
            profile = db.get(Profile, active_profile_id)
            if profile is not None:
                try:
                    backup_record = await scheduler.backup_before_manual_stop(
                        db,
                        profile,
                        datetime.now(timezone.utc),  # noqa: UP017
                    )
                except (BackupError, InvalidTransition, ValueError) as exc:
                    raise HTTPException(
                        409,
                        f"The pre-stop backup failed, so Blockstead left the server running: {exc}",
                    ) from exc
        try:
            graceful = await manager.stop()
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        if graceful:
            log.info("Stopped the managed server")
            app.state.active_profile_id = None
            if active_profile_id:
                stopped_profile = db.get(Profile, active_profile_id)
                if stopped_profile is not None:
                    refresh_profile_facts([stopped_profile], db)
        else:
            log.warning("The managed server did not stop before the timeout")
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=active_profile_id,
                category="server_stop",
                result="success" if graceful else "failed",
                safe_detail=(
                    "Stopped the managed Minecraft server"
                    if graceful
                    else "The managed Minecraft server did not stop before the timeout"
                ),
            )
        )
        db.commit()
        return {
            **manager.snapshot(),
            "graceful": graceful,
            "profile_id": app.state.active_profile_id,
            "backup": backup_payload(backup_record) if backup_record else None,
        }

    @app.post("/api/v1/server/force-stop", status_code=202)
    async def process_force_stop(request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        active_profile_id = app.state.active_profile_id
        try:
            await manager.force_stop()
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        log.warning("Force-stopped the managed server")
        app.state.active_profile_id = None
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=active_profile_id,
                category="server_stop",
                result="forced",
                safe_detail="Force-stopped the managed Minecraft server",
            )
        )
        db.commit()
        return {**manager.snapshot(), "profile_id": None}

    @app.websocket("/api/v1/server/logs/ws")
    async def logs_socket(websocket: WebSocket) -> None:
        def session_is_valid(token: str) -> bool:
            with factory() as db:
                session = db.scalar(
                    select(LoginSession).where(LoginSession.token_hash == digest(token))
                )
                if session is None:
                    return False
                now = datetime.now(timezone.utc)  # noqa: UP017
                if session.expires_at.replace(tzinfo=timezone.utc) <= now:  # noqa: UP017
                    db.delete(session)
                    db.commit()
                    return False
                return db.get(Administrator, session.admin_id) is not None

        origin = websocket.headers.get("origin")
        token = websocket.cookies.get(SESSION_COOKIE)
        if origin not in config.origins or not token or not session_is_valid(token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        subscription: asyncio.Task[None] | None = None
        auth_watch: asyncio.Task[None] | None = None

        async def close_when_session_ends() -> None:
            while True:
                await asyncio.sleep(float(app.state.websocket_auth_recheck_seconds))
                if not await asyncio.to_thread(session_is_valid, token):
                    await websocket.close(code=1008)
                    return

        try:
            for event in manager.logs():
                await websocket.send_json(event.__dict__)
            subscription = asyncio.create_task(
                manager.subscribe(lambda event: websocket.send_json(event.__dict__))
            )
            auth_watch = asyncio.create_task(close_when_session_ends())
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            tasks = [task for task in (subscription, auth_watch) if task is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    static_dir = resolve_static_dir(config.static_dir)
    if static_dir is None:
        # Serving only the API looks healthy to the installer, so say so plainly.
        log.warning(
            "The built dashboard was not found; serving the API only. "
            "Build frontend/dist or set BLOCKSTEAD_STATIC_DIR."
        )
    else:
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
