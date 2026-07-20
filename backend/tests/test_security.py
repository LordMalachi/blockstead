import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from blockstead.config import Settings
from blockstead.security import LoginLimiter


def test_login_limiter_bounds_and_prunes_tracked_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter([0.0, 1.0, 2.0, 20.0])
    monkeypatch.setattr("blockstead.security.time.monotonic", lambda: next(clock))
    limiter = LoginLimiter(attempts=5, window_seconds=5, max_keys=2)

    limiter.fail("first")
    limiter.fail("second")
    limiter.fail("third")
    assert list(limiter._events) == ["second", "third"]

    limiter.fail("current")
    assert list(limiter._events) == ["current"]


def test_login_limiter_rejects_only_an_additional_failed_attempt() -> None:
    limiter = LoginLimiter(attempts=2, window_seconds=300)
    limiter.fail("owner")
    limiter.fail("owner")

    with pytest.raises(HTTPException) as limited:
        limiter.fail("owner")

    assert limited.value.status_code == 429
    limiter.clear("owner")
    limiter.fail("owner")


def test_session_duration_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(session_hours=0)
