import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import psutil
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import Base, create_session_factory
from .import_scan import canonical_child, scan_server
from .models import Administrator, AuditEvent, LoginSession, Profile, Schedule
from .process import InvalidTransition, ProcessManager
from .scheduler import Scheduler
from .schemas import (
    CommandRequest,
    Credentials,
    ImportRequest,
    PlayerActionRequest,
    ProfileCreate,
    ScheduleRequest,
    StartRequest,
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


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    config.prepare()
    factory = create_session_factory(config.data_dir / "blockstead.db")
    manager = ProcessManager()
    limiter = LoginLimiter()
    psutil.cpu_percent(interval=None)  # prime so later non-blocking samples are meaningful

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine = factory.kw["bind"]
        Base.metadata.create_all(engine)
        scheduler.begin()
        yield
        await scheduler.close()
        await manager.close()

    app = FastAPI(title="Blockstead API", version="0.1.0", lifespan=lifespan)
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
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
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
        return {"status": "ok"}

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
        if profile.distribution != "vanilla":
            raise HTTPException(
                409, "Only vanilla server.jar profiles can be launched in this milestone."
            )
        jar = directory / "server.jar"
        eula = directory / "eula.txt"
        if not jar.is_file():
            raise HTTPException(409, "This vanilla profile does not contain server.jar.")
        if (
            not eula.is_file()
            or "eula=true" not in eula.read_text(encoding="utf-8", errors="replace").lower()
        ):
            raise HTTPException(
                409, "Accept the Minecraft EULA in eula.txt before starting this server."
            )
        return (("java", "-jar", str(jar), "nogui"), directory, "Vanilla Minecraft")

    @app.get("/api/v1/server/logs")
    def process_logs(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        return [event.__dict__ for event in manager.logs()]

    @app.get("/api/v1/schedules")
    def list_schedules(request: Request, db: Db) -> list[dict[str, object]]:
        current(request, db)
        return [{"id": s.id, "profile_id": s.profile_id, "enabled": s.enabled, "start_time": s.start_time, "stop_time": s.stop_time, "backup_before_stop": s.backup_before_stop, "power_off_after_stop": s.power_off_after_stop, "wake_time": s.wake_time} for s in db.scalars(select(Schedule)).all()]

    @app.put("/api/v1/schedules/{profile_id}")
    def save_schedule(profile_id: str, payload: ScheduleRequest, request: Request, db: Db) -> dict[str, object]:
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
        db.add(AuditEvent(admin_id=admin.id, category="schedule_update", result="success", safe_detail=f"Updated schedule for profile {profile_id}"))
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
        try:
            for event in manager.logs():
                await websocket.send_json(event.__dict__)
            await manager.subscribe(lambda event: websocket.send_json(event.__dict__))
        except (WebSocketDisconnect, RuntimeError):
            return

    static_dir = Path(__file__).parents[3] / "frontend" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
