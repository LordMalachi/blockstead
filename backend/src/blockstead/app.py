import asyncio
import json
import logging
import re
import secrets
import shutil
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

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
    create_backup_archive,
    mirror_backup_archive,
    perform_restore,
    plan_restore,
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
from .diagnostics import attach_logging, build_report
from .distributions import (
    DISTRIBUTIONS,
    LaunchPlanError,
    launch_arguments,
    required_java_major,
)
from .extension_ops import (
    MAX_UPLOAD_BYTES,
    ExtensionOpsError,
    place_upload,
    set_all_enabled,
    set_enabled,
)
from .extension_ops import (
    remove as remove_extension,
)
from .extensions import read_extensions
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
    promote_staging,
    purge_stale_uploads,
    safe_relative_path,
    scan_server,
)
from .java_runtime import discover_java_runtimes, find_java
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
    BackupRecord,
    LoginSession,
    MetricSample,
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
    join_details,
    minecraft_status,
    read_properties,
    world_size,
)
from .process import InvalidTransition, ProcessManager
from .provisioning import (
    DIRECTORY_PATTERN,
    USER_AGENT,
    ProvisionError,
    download_verified_file,
    list_versions,
    provision_profile,
)
from .retention import enforce_retention
from .scheduler import Scheduler, automation_steps, next_executions, parse_weekdays
from .schemas import (
    PROJECT_ID_PATTERN,
    AutomationEventRequest,
    AutomationRunRequest,
    BackupPolicyRequest,
    CommandRequest,
    Credentials,
    CurseForgeKeyRequest,
    EulaRequest,
    ImportRequest,
    ImportUploadFinish,
    ImportUploadStart,
    InstallRequest,
    ModConfigUpdateRequest,
    ModpackInstallRequest,
    NotificationPreferencesRequest,
    PlayerActionRequest,
    ProfileCreate,
    ProvisionRequest,
    RawSettingsUpdateRequest,
    ScheduleRequest,
    SettingsUpdateRequest,
    StartRequest,
    ToggleAllRequest,
    ToggleRequest,
    UpdateRequest,
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
from .server_files import read_players, read_settings
from .server_settings import (
    SettingsConflictError,
    SettingsValidationError,
    apply_raw_settings,
    apply_settings_update,
    preview_raw_settings,
    preview_settings_update,
    read_raw_settings,
)
from .shared_map import read_shared_map

log = logging.getLogger("blockstead.api")


def error(status_code: int, code: str, message: str, recovery: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    if recovery:
        body["error"]["recovery"] = recovery  # type: ignore[index]
    return JSONResponse(status_code=status_code, content=body)


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

    metrics_task: asyncio.Task[None] | None = None
    update_task: asyncio.Task[None] | None = None
    update_wakeup = asyncio.Event()
    update_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal metrics_task, update_task
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
                            result=(
                                "success" if helper_result.state == "succeeded" else "failed"
                            ),
                            safe_detail=marker,
                            created_at=helper_result.at,
                        )
                    )
            db.commit()
        metrics_task = asyncio.create_task(metrics_loop())
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
        for task in (metrics_task, update_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        metrics_task = None
        update_task = None
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
    app.state.websocket_auth_recheck_seconds = 5.0
    # Profiles with a restore in flight; starting or backing up one is refused.
    restoring_profiles: set[str] = set()
    # Long-running world mutations must finish before the service can hand an
    # update to the root helper. Tokens make concurrent backups independently
    # visible without holding the update lock for their full duration.
    critical_update_operations: set[str] = set()

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

    last_observed_state = manager.snapshot()["state"]

    async def metrics_loop() -> None:
        nonlocal last_observed_state
        while True:
            try:
                await asyncio.to_thread(sample_active_profile)
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
            and (
                config.data_dir / "backups" / record.profile_id / record.file_name
            ).is_file()
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
            "included_paths": json.loads(record.included_paths)
            if record.included_paths
            else [],
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

    @app.get("/api/v1/profiles")
    def list_profiles(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
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
    def download_backup(
        profile_id: str, backup_id: str, request: Request, db: Db
    ) -> FileResponse:
        current(request, db)
        record = db.get(BackupRecord, backup_id)
        if record is None or record.profile_id != profile_id:
            raise HTTPException(404, "That backup was not found for this server.")
        if record.status != "completed" or not record.file_name:
            raise HTTPException(409, "Only a completed backup can be saved elsewhere.")
        if (
            "/" in record.file_name
            or "\\" in record.file_name
            or record.file_name.startswith(".")
        ):
            raise HTTPException(409, "This backup's archive name is not usable.")
        archive = config.data_dir / "backups" / profile_id / record.file_name
        if not archive.is_file():
            raise HTTPException(409, "This backup archive is no longer on disk.")
        return FileResponse(archive, filename=record.file_name, media_type="application/gzip")

    @app.post("/api/v1/profiles/{profile_id}/backups", status_code=201)
    async def create_backup(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
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
        running = (
            app.state.active_profile_id == profile.id
            and snapshot["state"] in {"RUNNING", "STARTING", "DEGRADED"}
        )
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
            raise HTTPException(
                409, "Only a completed backup with a manifest can be restored."
            )
        try:
            server_directory = canonical_child(
                Path(profile.server_directory), config.server_root
            )
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
        return {
            "keep_count": profile.backup_keep_count,
            "keep_days": profile.backup_keep_days,
            "max_total_mb": profile.backup_max_total_mb,
            "redundancy_enabled": profile.backup_redundancy_enabled,
            "destinations": configured_backup_destinations(profile),
        }

    @app.get("/api/v1/profiles/{profile_id}/backup-policy")
    def read_backup_policy(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
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

    def profile_directory(profile_id: str, db: Session) -> Path:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        try:
            return canonical_child(Path(profile.server_directory), config.server_root)
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "The profile folder is no longer inside the allowed server root."
            ) from exc

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
    def profile_settings_raw(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
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

    @app.get("/api/v1/profiles/{profile_id}/extensions")
    def profile_extensions(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        return read_extensions(directory, profile.distribution).model_dump()

    @app.get("/api/v1/profiles/{profile_id}/shared-map")
    def profile_shared_map(profile_id: str, request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        return read_shared_map(directory, profile.distribution).model_dump()

    def extension_context(profile_id: str, db: Session) -> tuple[Profile, Path]:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            raise HTTPException(409, "This server distribution does not load plugins or mods.")
        return profile, directory / info.extension_directory

    def require_published_checksums(planned: list[PlannedFile]) -> None:
        """Catalog installs must have a publisher digest, not merely HTTPS."""
        missing = [
            item.file_name for item in planned if not item.checksum_algorithm or not item.checksum
        ]
        if missing:
            raise HTTPException(
                409,
                "Blockstead will not automatically install files without a published "
                f"checksum: {', '.join(missing)}.",
            )

    async def stage_extension_install(
        extension_dir: Path,
        planned: list[PlannedFile],
        *,
        replace_names: frozenset[str] = frozenset(),
    ) -> tuple[list[dict[str, object]], list[str]]:
        """Download a catalog plan outside the live loadout, then promote it.

        A failed dependency download used to leave the preceding jars live. A
        staging directory guarantees the loadout is untouched until every new
        file has downloaded and passed its published checksum.
        """
        require_published_checksums(planned)
        names = [item.file_name for item in planned]
        if len(names) != len(set(names)):
            raise HTTPException(409, "The catalog returned duplicate extension file names.")
        extension_dir.mkdir(mode=0o755, exist_ok=True)
        staging = extension_dir / f".blockstead-install-{secrets.token_hex(8)}"
        staging.mkdir(mode=0o700)
        staged: list[tuple[PlannedFile, str]] = []
        skipped: list[str] = []
        try:
            for planned_file in planned:
                target = extension_dir / planned_file.file_name
                if target.exists() and planned_file.file_name not in replace_names:
                    skipped.append(planned_file.file_name)
                    continue
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

            # Recheck immediately before moving anything into the live folder.
            # The server is stopped, but a second browser request can still race
            # this one; never overwrite a separately installed extension.
            for planned_file, _ in staged:
                target = extension_dir / planned_file.file_name
                if target.exists() and planned_file.file_name not in replace_names:
                    raise HTTPException(
                        409,
                        f"A file named {planned_file.file_name} was installed while this "
                        "catalog download was in progress.",
                    )
            for planned_file, _ in staged:
                (staging / planned_file.file_name).replace(
                    extension_dir / planned_file.file_name
                )
        except OSError as exc:
            raise HTTPException(
                409, "Blockstead could not place the verified extension files."
            ) from exc
        finally:
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
                list_catalog_versions = (
                    hangar_versions if source == "hangar" else modrinth_versions
                )
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

    @app.post("/api/v1/profiles/{profile_id}/extensions/update")
    async def extension_apply_update(
        profile_id: str, payload: UpdateRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        view = read_extensions(profile_directory(profile_id, db), profile.distribution)
        entry = next(
            (item for item in view.entries if item.file_name == payload.file_name), None
        )
        if entry is None or not entry.sha512:
            raise HTTPException(404, "That file is not in the live extensions folder.")
        try:
            found = await modrinth_check_updates(
                http_client, profile.distribution, profile.minecraft_version, [entry.sha512]
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        planned = found.get(entry.sha512)
        if planned is None:
            raise HTTPException(409, "No newer compatible version is known for that file.")
        if planned.file_name != entry.file_name and (extension_dir / planned.file_name).exists():
            raise HTTPException(409, "A file with the new version's name already exists.")
        try:
            update_plan = await plan_install(
                http_client,
                profile.distribution,
                profile.minecraft_version,
                planned.project_id,
                planned.version_id,
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc
        if (
            not update_plan
            or update_plan[0].project_id != planned.project_id
            or update_plan[0].file_name != planned.file_name
        ):
            raise HTTPException(409, "Modrinth returned an unusable extension update plan.")
        installed, _ = await stage_extension_install(
            extension_dir,
            update_plan,
            replace_names=frozenset({entry.file_name}),
        )
        sha256 = next(
            (
                str(item["sha256"])
                for item in installed
                if item["file_name"] == planned.file_name
            ),
            None,
        )
        if sha256 is None:
            raise HTTPException(409, "The updated extension file was not installed.")
        if planned.file_name != entry.file_name:
            try:
                remove_extension(extension_dir, entry.file_name)
            except ExtensionOpsError as exc:
                raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                profile_id=profile_id,
                category="extension_update",
                result="success",
                safe_detail=(
                    f"Updated {entry.file_name} to {planned.file_name} (sha256 {sha256})"
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
            "restart_required": True,
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
            "warnings": [warning.model_dump() for warning in view.warnings],
            "restart_required": True,
        }

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
    async def profile_overview(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
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
            sample = await asyncio.to_thread(
                collect_metric_sample, profile, include_process=active
            )
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

        join = join_details(
            properties, request.url.hostname, config.public_minecraft_port
        )
        status = await minecraft_status(properties) if active and state == "RUNNING" else None
        configured_max = 20
        try:
            possible_max = int(properties.get("max-players", "20"))
            if 1 <= possible_max <= 1000:
                configured_max = possible_max
        except ValueError:
            pass
        players = status or {"online": None, "max": configured_max, "sample": []}
        players["available"] = status is not None

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
        upcoming = next_executions(
            schedule, pending_events, datetime.now().astimezone(), limit=1
        )
        next_operation = (
            {"label": upcoming[0]["label"], "at": upcoming[0]["at"]}
            if upcoming
            else None
        )

        warnings: list[dict[str, str]] = []
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
            "capabilities": {
                "tps": False,
                "mspt": False,
                "distribution_label": info.label,
            },
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

    def diagnostics_payload(db: Session) -> dict[str, object]:
        return build_report(
            config=config,
            buffer=diagnostics,
            server={**manager.snapshot(), "profile_id": app.state.active_profile_id},
            static_dir=resolve_static_dir(config.static_dir),
            db=db,
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
    def activity_report(event_id: str, request: Request, db: Db) -> Response:
        current(request, db)
        event = db.get(AuditEvent, event_id)
        if event is None:
            raise HTTPException(404, "That activity event was not found.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
        report = build_report(
            config=config,
            buffer=diagnostics,
            server={**manager.snapshot(), "profile_id": app.state.active_profile_id},
            static_dir=resolve_static_dir(config.static_dir),
            db=db,
            focus_event=event,
        )
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
                    profile = db.get(Profile, record.profile_id)
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
                                if profile is not None
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
                    "created_at": (
                        manager.state_changed_at.isoformat()
                    ),
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
    def system_diagnostics(request: Request, db: Db) -> dict[str, object]:
        current(request, db)
        return diagnostics_payload(db)

    @app.get("/api/v1/system/diagnostics/report")
    def system_diagnostics_report(request: Request, db: Db) -> Response:
        current(request, db)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")  # noqa: UP017
        return Response(
            content=json.dumps(diagnostics_payload(db), indent=2),
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
        if payload.run_at <= datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M"):
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
    def cancel_automation_event(
        profile_id: str, event_id: str, request: Request, db: Db
    ) -> None:
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
        if db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        return catalog_payload()

    @app.post("/api/v1/server/guided-command", status_code=202)
    async def guided_command(
        payload: GuidedCommandRequest, request: Request, db: Db
    ) -> dict[str, str]:
        admin = mutation(request, db)
        if db.get(Profile, payload.profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        if app.state.active_profile_id != payload.profile_id:
            raise HTTPException(409, "Start this profile before sending it a command.")
        try:
            command, safety = render_guided_command(payload.command_id, payload.values)
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
                        db, profile, datetime.now(timezone.utc)  # noqa: UP017
                    )
                except (BackupError, InvalidTransition, ValueError) as exc:
                    raise HTTPException(
                        409,
                        "The pre-stop backup failed, so Blockstead left the server running: "
                        f"{exc}",
                    ) from exc
        try:
            graceful = await manager.stop()
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        if graceful:
            log.info("Stopped the managed server")
            app.state.active_profile_id = None
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
