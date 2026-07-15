import asyncio
import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from . import __version__
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
from .import_scan import canonical_child, scan_server
from .java_runtime import discover_java_runtimes, find_java
from .models import Administrator, AuditEvent, LoginSession, Profile, Schedule
from .modpacks import (
    MAX_MRPACK_BYTES,
    ModpackError,
    fetch_mrpack,
    install_modpack,
    search_modpacks,
)
from .modrinth import ModrinthError, plan_install
from .modrinth import search as modrinth_search
from .process import InvalidTransition, ProcessManager
from .provisioning import (
    USER_AGENT,
    ProvisionError,
    download_verified_file,
    list_versions,
    provision_profile,
)
from .scheduler import Scheduler
from .schemas import (
    CommandRequest,
    Credentials,
    EulaRequest,
    ImportRequest,
    InstallRequest,
    ModpackInstallRequest,
    PlayerActionRequest,
    ProfileCreate,
    ProvisionRequest,
    ScheduleRequest,
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

log = logging.getLogger("blockstead.api")


def error(status_code: int, code: str, message: str, recovery: str | None = None) -> JSONResponse:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    if recovery:
        body["error"]["recovery"] = recovery  # type: ignore[index]
    return JSONResponse(status_code=status_code, content=body)


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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine = factory.kw["bind"]
        Base.metadata.create_all(engine)
        scheduler.begin()
        yield
        await scheduler.close()
        await manager.close()
        await http_client.aclose()

    app = FastAPI(title="Blockstead API", version=__version__, lifespan=lifespan)
    app.state.settings = config
    app.state.session_factory = factory
    app.state.process_manager = manager
    app.state.active_profile_id = None

    def get_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    Db = Annotated[Session, Depends(get_db)]

    async def scheduled_start(profile: Profile) -> None:
        arguments, cwd, label = launch_spec(profile, "normal")
        await manager.start(arguments, cwd=cwd, label=label)
        app.state.active_profile_id = profile.id

    scheduler = Scheduler(factory, manager, scheduled_start, config.data_dir)

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

    @app.post("/api/v1/imports/scan")
    def import_scan(payload: ImportRequest, request: Request, db: Db) -> dict[str, object]:
        mutation(request, db)
        try:
            return scan_server(Path(payload.path), config.server_root).model_dump()
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

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
                "is_fixture": p.is_fixture,
            }
            for p in db.scalars(select(Profile).order_by(Profile.created_at)).all()
        ]

    @app.post("/api/v1/profiles", status_code=201)
    def create_profile(payload: ProfileCreate, request: Request, db: Db) -> dict[str, object]:
        admin = mutation(request, db)
        try:
            result = scan_server(
                canonical_child(Path(payload.path), config.server_root), config.server_root
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        profile = Profile(
            name=payload.name.strip(),
            server_directory=result.canonical_path,
            distribution=result.distribution,
            minecraft_version=result.minecraft_version,
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
        try:
            result = await provision_profile(
                http_client,
                config.server_root,
                payload.directory_name,
                payload.distribution,
                payload.minecraft_version,
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
        admin: Administrator, db: Session, name: str, result_directory: str, version: str
    ) -> Profile:
        profile = Profile(
            name=name.strip(),
            server_directory=result_directory,
            distribution="fabric",
            minecraft_version=version,
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
            admin, db, payload.name, result.directory, result.minecraft_version
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
            admin, db, name, result.directory, result.minecraft_version
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
        try:
            arguments, cwd, label = launch_spec(profile, payload.mode)
            await manager.start(arguments, cwd=cwd, label=label)
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
            await manager.start(arguments, cwd=cwd, label=label)
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

    static_dir = Path(__file__).parents[3] / "frontend" / "dist"
    if static_dir.is_dir():
        app.mount("/", SpaStaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
