import asyncio
import json
import logging
import secrets
import shutil
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
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
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from . import __version__
from .backups import (
    BackupArchive,
    BackupError,
    RestoreError,
    create_backup_archive,
    perform_restore,
    plan_restore,
)
from .config import Settings
from .db import Base, create_session_factory
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
    set_enabled,
)
from .extension_ops import (
    remove as remove_extension,
)
from .extensions import read_extensions
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
    AuditEvent,
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
from .modrinth import ModrinthError, plan_install
from .modrinth import search as modrinth_search
from .overview import (
    join_details,
    minecraft_status,
    next_schedule_operation,
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
from .scheduler import Scheduler
from .schemas import (
    BackupPolicyRequest,
    CommandRequest,
    Credentials,
    EulaRequest,
    ImportRequest,
    ImportUploadFinish,
    ImportUploadStart,
    InstallRequest,
    ModConfigUpdateRequest,
    ModpackInstallRequest,
    PlayerActionRequest,
    ProfileCreate,
    ProvisionRequest,
    RawSettingsUpdateRequest,
    ScheduleRequest,
    SettingsUpdateRequest,
    StartRequest,
    ToggleRequest,
)
from .security import (
    SESSION_COOKIE,
    LoginLimiter,
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal metrics_task
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
            db.commit()
        scheduler.begin()
        metrics_task = asyncio.create_task(metrics_loop())
        yield
        if metrics_task is not None:
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass
            metrics_task = None
        await scheduler.close()
        await manager.close()
        await http_client.aclose()

    app = FastAPI(title="Blockstead API", version=__version__, lifespan=lifespan)
    app.state.settings = config
    app.state.session_factory = factory
    app.state.process_manager = manager
    app.state.active_profile_id = None
    # Profiles with a restore in flight; starting or backing up one is refused.
    restoring_profiles: set[str] = set()

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

    async def metrics_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(sample_active_profile)
            except Exception:
                log.exception("Could not record an overview metric sample")
            await asyncio.sleep(60)

    def get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    Db = Annotated[Session, Depends(get_db)]

    async def scheduled_start(profile: Profile) -> None:
        arguments, cwd, label = launch_spec(profile, "normal")
        await manager.start(arguments, cwd=cwd, label=label, owner=profile.id)
        app.state.active_profile_id = profile.id

    scheduler = Scheduler(
        factory, manager, scheduled_start, config.data_dir, config.server_root
    )

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
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "version": __version__,
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
        key = f"{request.client.host if request.client else 'unknown'}:{payload.username.lower()}"
        limiter.check(key)
        admin = db.scalar(select(Administrator).where(Administrator.username == payload.username))
        if admin is None or not verify_password(admin.password_hash, payload.password):
            limiter.fail(key)
            raise HTTPException(401, "The username or password was not accepted.")
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
        db.add(
            AuditEvent(
                admin_id=admin.id,
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

    @app.post("/api/v1/profiles/{profile_id}/backups", status_code=201)
    async def create_backup(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
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
        if archive is not None:
            record.file_name = archive.file_name
            record.manifest_name = archive.manifest_name
            record.sha256 = archive.sha256
            record.included_paths = json.dumps(list(archive.included_paths))
            record.size_bytes = archive.size_bytes
        if failure:
            record.status = "failed"
            record.result = failure
        else:
            assert archive is not None
            record.status = "completed"
            record.result = f"Protected {', '.join(archive.included_paths)}."
            enforce_retention(db, profile, config.data_dir)
        db.add(
            AuditEvent(
                admin_id=admin.id,
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
                    category="backup_restore",
                    result="failed",
                    safe_detail=f"Restore failed for {profile.name}: {exc}",
                )
            )
            db.commit()
            raise HTTPException(409, str(exc)) from exc
        finally:
            restoring_profiles.discard(profile.id)
        db.add(
            AuditEvent(
                admin_id=admin.id,
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

    def policy_payload(profile: Profile) -> dict[str, int | None]:
        return {
            "keep_count": profile.backup_keep_count,
            "keep_days": profile.backup_keep_days,
            "max_total_mb": profile.backup_max_total_mb,
        }

    @app.get("/api/v1/profiles/{profile_id}/backup-policy")
    def read_backup_policy(
        profile_id: str, request: Request, db: Db
    ) -> dict[str, int | None]:
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
        expired = enforce_retention(db, profile, config.data_dir)
        db.add(
            AuditEvent(
                admin_id=admin.id,
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
        db.add(
            AuditEvent(
                admin_id=admin.id,
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
        db.add(
            AuditEvent(
                admin_id=admin.id,
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

    def extension_context(profile_id: str, db: Session) -> tuple[Profile, Path]:
        profile = db.get(Profile, profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        directory = profile_directory(profile_id, db)
        info = DISTRIBUTIONS.get(profile.distribution, DISTRIBUTIONS["unknown"])
        if info.extension_directory is None:
            raise HTTPException(409, "This server distribution does not load plugins or mods.")
        return profile, directory / info.extension_directory

    def require_server_stopped() -> None:
        if manager.state.value not in {"STOPPED", "CRASHED"}:
            raise HTTPException(409, "Stop the server before changing mods or configuration.")

    @app.get("/api/v1/profiles/{profile_id}/modrinth/search")
    async def extension_search(
        profile_id: str, query: str, request: Request, db: Db
    ) -> dict[str, object]:
        current(request, db)
        profile, _ = extension_context(profile_id, db)
        if not query.strip() or len(query) > 100:
            raise HTTPException(422, "Enter a search of at most 100 characters.")
        try:
            projects = await modrinth_search(
                http_client, profile.distribution, profile.minecraft_version, query.strip()
            )
        except ModrinthError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "minecraft_version": profile.minecraft_version,
            "projects": [project.model_dump() for project in projects],
        }

    @app.post("/api/v1/profiles/{profile_id}/extensions/install", status_code=201)
    async def extension_install(
        profile_id: str, payload: InstallRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        require_server_stopped()
        profile, extension_dir = extension_context(profile_id, db)
        try:
            planned = await plan_install(
                http_client,
                profile.distribution,
                profile.minecraft_version,
                payload.project_id,
                payload.version_id,
            )
        except ModrinthError as exc:
            raise HTTPException(400, str(exc)) from exc
        extension_dir.mkdir(mode=0o755, exist_ok=True)
        installed: list[dict[str, object]] = []
        skipped: list[str] = []
        try:
            for planned_file in planned:
                if (extension_dir / planned_file.file_name).exists():
                    skipped.append(planned_file.file_name)
                    continue
                sha256 = await download_verified_file(
                    http_client,
                    planned_file.url,
                    extension_dir,
                    planned_file.file_name,
                    planned_file.checksum_algorithm,
                    planned_file.checksum,
                )
                installed.append(
                    {
                        "file_name": planned_file.file_name,
                        "version_number": planned_file.version_number,
                        "required_by": planned_file.required_by,
                        "sha256": sha256,
                    }
                )
        except ProvisionError as exc:
            raise HTTPException(400, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="extension_install",
                result="success",
                safe_detail=(
                    f"Installed {len(installed)} file(s) from Modrinth project {payload.project_id}"
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
        db.add(
            AuditEvent(
                admin_id=admin.id,
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

        join = join_details(properties, request.url.hostname)
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
        next_operation = (
            next_schedule_operation(
                schedule.enabled,
                schedule.start_time,
                schedule.stop_time,
                datetime.now().astimezone(),
            )
            if schedule
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
            if profile.id not in event.safe_detail and profile.name not in event.safe_detail:
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

    @app.get("/api/v1/schedules")
    def list_schedules(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        return [
            {
                "id": s.id,
                "profile_id": s.profile_id,
                "enabled": s.enabled,
                "start_time": s.start_time,
                "stop_time": s.stop_time,
                "backup_before_stop": s.backup_before_stop,
                "power_off_after_stop": s.power_off_after_stop,
                "wake_time": s.wake_time,
            }
            for s in db.scalars(select(Schedule)).all()
        ]

    @app.put("/api/v1/schedules/{profile_id}")
    def save_schedule(
        profile_id: str, payload: ScheduleRequest, request: Request, db: Db
    ) -> dict[str, object]:
        admin = mutation(request, db)
        if payload.profile_id != profile_id or db.get(Profile, profile_id) is None:
            raise HTTPException(404, "That profile was not found.")
        if payload.power_off_after_stop and not payload.stop_time:
            raise HTTPException(422, "A computer shutdown needs a server stop time.")
        schedule = db.scalar(select(Schedule).where(Schedule.profile_id == profile_id))
        if schedule is None:
            schedule = Schedule(profile_id=profile_id)
            db.add(schedule)
        for name, value in payload.model_dump().items():
            setattr(schedule, name, value)
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="schedule_update",
                result="success",
                safe_detail=f"Updated schedule for profile {profile_id}",
            )
        )
        db.commit()
        return {"id": schedule.id, **payload.model_dump()}

    @app.post("/api/v1/server/start", status_code=202)
    async def process_start(payload: StartRequest, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        profile = db.get(Profile, payload.profile_id)
        if profile is None:
            raise HTTPException(404, "That profile was not found.")
        if profile.id in restoring_profiles:
            raise HTTPException(
                409, "A restore is in progress for this server. Wait for it to finish."
            )
        try:
            arguments, cwd, label = launch_spec(profile, payload.mode)
            await manager.start(arguments, cwd=cwd, label=label, owner=profile.id)
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
                category="server_start",
                result="accepted",
                safe_detail=f"Started {profile.distribution} profile {profile.name}",
            )
        )
        db.commit()
        app.state.active_profile_id = profile.id
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
                category="console_command",
                result="accepted",
                safe_detail="Sent one Minecraft console command; content omitted",
            )
        )
        db.commit()
        return {"status": "accepted"}

    @app.post("/api/v1/server/restart", status_code=202)
    async def process_restart(payload: StartRequest, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
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
            arguments, cwd, label = launch_spec(profile, payload.mode)
            await manager.start(arguments, cwd=cwd, label=label, owner=profile.id)
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        db.add(
            AuditEvent(
                admin_id=admin.id,
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
                category="player_action",
                result="accepted",
                safe_detail=f"Requested {payload.action} for {payload.player}",
            )
        )
        db.commit()
        return {"status": "accepted", "command": payload.console_command}

    @app.post("/api/v1/server/stop", status_code=202)
    async def process_stop(request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        try:
            graceful = await manager.stop()
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        if graceful:
            app.state.active_profile_id = None
        return {
            **manager.snapshot(),
            "graceful": graceful,
            "profile_id": app.state.active_profile_id,
        }

    @app.post("/api/v1/server/force-stop", status_code=202)
    async def process_force_stop(request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        try:
            await manager.force_stop()
        except InvalidTransition as exc:
            raise HTTPException(409, str(exc)) from exc
        app.state.active_profile_id = None
        return {**manager.snapshot(), "profile_id": None}

    @app.websocket("/api/v1/server/logs/ws")
    async def logs_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        token = websocket.cookies.get(SESSION_COOKIE)
        if origin not in config.origins or not token:
            await websocket.close(code=1008)
            return
        with factory() as db:
            session = db.scalar(
                select(LoginSession).where(LoginSession.token_hash == digest(token))
            )
            now = datetime.now(timezone.utc)  # noqa: UP017
            if (
                session is None
                or session.expires_at.replace(tzinfo=timezone.utc) <= now  # noqa: UP017
                or db.get(Administrator, session.admin_id) is None
            ):
                await websocket.close(code=1008)
                return
        await websocket.accept()
        subscription: asyncio.Task[None] | None = None
        try:
            for event in manager.logs():
                await websocket.send_json(event.__dict__)
            subscription = asyncio.create_task(
                manager.subscribe(lambda event: websocket.send_json(event.__dict__))
            )
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            if subscription is not None:
                subscription.cancel()
                await asyncio.gather(subscription, return_exceptions=True)

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
