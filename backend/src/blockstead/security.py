import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Administrator, LoginSession

SESSION_COOKIE = "blockstead_session"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False


def create_session(db: Session, admin: Administrator, hours: int) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            admin_id=admin.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=hours),  # noqa: UP017
        )
    )
    db.commit()
    return token, csrf


class LoginLimiter:
    def __init__(self, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts, self.window = attempts, window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now, events = time.monotonic(), self._events[key]
        while events and events[0] < now - self.window:
            events.popleft()
        if len(events) >= self.attempts:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Try again in a few minutes.",
            )

    def fail(self, key: str) -> None:
        self._events[key].append(time.monotonic())

    def clear(self, key: str) -> None:
        self._events.pop(key, None)


def authenticate_request(request: Request, db: Session) -> tuple[Administrator, LoginSession]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token)))
    now = datetime.now(timezone.utc)  # noqa: UP017
    if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= now:  # noqa: UP017
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Your session has expired.")
    admin = db.get(Administrator, session.admin_id)
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Your session is no longer valid.")
    return admin, session


def require_mutation_security(
    request: Request, session: LoginSession, origins: frozenset[str]
) -> None:
    origin = request.headers.get("origin")
    csrf = request.headers.get("x-csrf-token", "")
    if origin not in origins:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="This request came from an untrusted page."
        )
    if not csrf or not secrets.compare_digest(digest(csrf), session.csrf_hash):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="The security token is missing or invalid. Refresh and try again.",
        )
