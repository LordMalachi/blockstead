import hashlib
import secrets
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Administrator, LoginSession

SESSION_COOKIE = "blockstead_session"
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


class PasswordHashError(RuntimeError):
    """The stored administrator password hash could not be verified safely."""


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return _hasher.verify(encoded, password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError) as exc:
        raise PasswordHashError("The stored password hash is invalid.") from exc


def create_session(db: Session, admin: Administrator, hours: int) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)  # noqa: UP017
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    db.add(
        LoginSession(
            admin_id=admin.id,
            token_hash=digest(token),
            csrf_hash=digest(csrf),
            expires_at=now + timedelta(hours=hours),
        )
    )
    db.commit()
    return token, csrf


class LoginLimiter:
    def __init__(
        self, attempts: int = 5, window_seconds: int = 300, max_keys: int = 1024
    ) -> None:
        if attempts < 1 or window_seconds < 0 or max_keys < 1:
            raise ValueError("Login limiter settings must be positive.")
        self.attempts, self.window, self.max_keys = attempts, window_seconds, max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        for key, events in list(self._events.items()):
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[key] = events
            if len(events) >= self.attempts:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many login attempts. Try again in a few minutes.",
                )
            events.append(now)
            self._events.move_to_end(key)

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


def authenticate_request(request: Request, db: Session) -> tuple[Administrator, LoginSession]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token)))
    now = datetime.now(timezone.utc)  # noqa: UP017
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Your session has expired.")
    if session.expires_at.replace(tzinfo=timezone.utc) <= now:  # noqa: UP017
        db.delete(session)
        db.commit()
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
