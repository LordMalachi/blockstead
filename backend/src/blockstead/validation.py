"""Structured field-level validation errors.

Implements the shared contract in ``docs/validation-contract.md``. The frontend's
``normalizeServerDirectoryName`` (``frontend/src/lib/server-directory.ts``) must produce
identical output to :func:`normalize_server_directory_name` for the same input; both sides
carry a test asserting the same table of examples.
"""

import re
import secrets
from collections.abc import Callable, Mapping
from enum import StrEnum

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel

from .provisioning import DIRECTORY_PATTERN

__all__ = [
    "FieldError",
    "FieldValidationError",
    "ReasonCode",
    "describe_directory_name",
    "field_errors_from_request_validation",
    "normalize_server_directory_name",
    "suggest_available_directory_name",
]


class ReasonCode(StrEnum):
    """Stable machine codes for ``fields[].reason``. Never localized or reworded."""

    REQUIRED = "REQUIRED"
    TOO_SHORT = "TOO_SHORT"
    TOO_LONG = "TOO_LONG"
    INVALID_CHARACTERS = "INVALID_CHARACTERS"
    UPPERCASE_NOT_ALLOWED = "UPPERCASE_NOT_ALLOWED"
    MUST_START_WITH_LETTER_OR_NUMBER = "MUST_START_WITH_LETTER_OR_NUMBER"
    MUST_END_WITH_LETTER_OR_NUMBER = "MUST_END_WITH_LETTER_OR_NUMBER"
    CONSECUTIVE_SEPARATORS = "CONSECUTIVE_SEPARATORS"
    RESERVED_NAME = "RESERVED_NAME"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    NOT_ALLOWED_VALUE = "NOT_ALLOWED_VALUE"
    PATH_NOT_WRITABLE = "PATH_NOT_WRITABLE"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    INCOMPATIBLE_LOADER = "INCOMPATIBLE_LOADER"


class FieldError(BaseModel):
    """One entry of the error envelope's ``error.fields`` array."""

    field: str
    reason: ReasonCode
    message: str
    rule: str | None = None
    suggestion: str | None = None


class FieldValidationError(HTTPException):
    """An HTTPException whose JSON body includes structured field detail.

    Raise this instead of a plain ``HTTPException`` wherever a route can name the
    request field responsible for the failure, so the dashboard can highlight the
    right control.
    """

    def __init__(
        self,
        status_code: int,
        message: str,
        fields: list[FieldError],
        recovery: str | None = None,
        code: str = "REQUEST_INVALID",
    ) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.fields = fields
        self.recovery = recovery
        self.code = code


_DISALLOWED_RUN = re.compile(r"[^a-z0-9_-]+")
_REPEATED_HYPHEN = re.compile(r"-{2,}")
_REPEATED_UNDERSCORE = re.compile(r"_{2,}")
_LEADING_NON_ALNUM = re.compile(r"^[^a-z0-9]+")
_TRAILING_NON_ALNUM = re.compile(r"[^a-z0-9]+$")
_ALLOWED_EDGE_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")

DIRECTORY_NAME_RULE = (
    "Use 1 to 64 characters: lowercase letters, numbers, hyphens and underscores, "
    "starting and ending with a letter or number."
)


def normalize_server_directory_name(value: str, fallback: str = "minecraft-server") -> str:
    """Turn a user-facing folder label into the portable server-directory form.

    Trim, lowercase, replace every run of disallowed characters with a single ``-``,
    collapse repeated separators, strip leading and trailing non-alphanumerics, truncate
    to 64 characters, strip trailing non-alphanumerics again, and fall back to
    ``minecraft-server`` (or the given fallback) when nothing survives. The result always
    matches ``^[a-z0-9][a-z0-9_-]{0,63}$``.
    """
    normalized = value.strip().lower()
    normalized = _DISALLOWED_RUN.sub("-", normalized)
    normalized = _REPEATED_HYPHEN.sub("-", normalized)
    normalized = _REPEATED_UNDERSCORE.sub("_", normalized)
    normalized = _LEADING_NON_ALNUM.sub("", normalized)
    normalized = _TRAILING_NON_ALNUM.sub("", normalized)
    normalized = normalized[:64]
    normalized = _TRAILING_NON_ALNUM.sub("", normalized)
    return normalized or fallback


def describe_directory_name(value: str) -> FieldError | None:
    """Return the most specific reason a server folder name fails, or ``None`` if valid.

    ``DIRECTORY_PATTERN`` alone permits a trailing ``-`` or ``_`` (the pattern only
    anchors the *first* character to a letter or number), but the dashboard also wants
    the name to *end* clean, so this checks that edge explicitly rather than relying on
    the bare pattern.
    """
    if DIRECTORY_PATTERN.match(value) and value[-1] in _ALLOWED_EDGE_CHARS:
        return None
    suggestion = normalize_server_directory_name(value)
    if not value:
        reason = ReasonCode.REQUIRED
        message = "A server folder name is required."
    elif len(value) > 64:
        reason = ReasonCode.TOO_LONG
        message = "Use 64 characters or fewer."
    elif value != value.lower():
        reason = ReasonCode.UPPERCASE_NOT_ALLOWED
        message = "Use only lowercase letters."
    elif _DISALLOWED_RUN.search(value):
        reason = ReasonCode.INVALID_CHARACTERS
        message = "Use only lowercase letters, numbers, hyphens and underscores."
    elif value[0] not in _ALLOWED_EDGE_CHARS:
        reason = ReasonCode.MUST_START_WITH_LETTER_OR_NUMBER
        message = "Start the name with a letter or number."
    else:
        reason = ReasonCode.MUST_END_WITH_LETTER_OR_NUMBER
        message = "End the name with a letter or number."
    return FieldError(
        field="directory_name",
        reason=reason,
        message=message,
        rule=DIRECTORY_NAME_RULE,
        suggestion=suggestion,
    )


def suggest_available_directory_name(
    base: str, exists: Callable[[str], bool], limit: int = 500
) -> str:
    """Return the first well-formed, unused variant of ``base`` (``base``, ``base-2``, …).

    ``exists`` is called with each pattern-valid candidate and should return whether that
    name is already taken. The result always matches ``^[a-z0-9][a-z0-9_-]{0,63}$``.
    """
    normalized = normalize_server_directory_name(base)
    if not exists(normalized):
        return normalized
    trimmed = normalized.rstrip("-_") or normalized
    for suffix_number in range(2, limit + 1):
        suffix = f"-{suffix_number}"
        candidate = f"{trimmed[: 64 - len(suffix)]}{suffix}"
        if not exists(candidate):
            return candidate
    return f"{trimmed[:55]}-{secrets.token_hex(4)}"


_PYDANTIC_TYPE_REASONS: dict[str, ReasonCode] = {
    "missing": ReasonCode.REQUIRED,
    "string_too_short": ReasonCode.TOO_SHORT,
    "too_short": ReasonCode.TOO_SHORT,
    "string_too_long": ReasonCode.TOO_LONG,
    "too_long": ReasonCode.TOO_LONG,
    "string_pattern_mismatch": ReasonCode.INVALID_CHARACTERS,
    "literal_error": ReasonCode.NOT_ALLOWED_VALUE,
    "enum": ReasonCode.NOT_ALLOWED_VALUE,
}

_PYDANTIC_TYPE_MESSAGES: dict[ReasonCode, str] = {
    ReasonCode.REQUIRED: "This is required.",
    ReasonCode.TOO_SHORT: "That's too short.",
    ReasonCode.TOO_LONG: "That's too long.",
    ReasonCode.INVALID_CHARACTERS: "That includes characters that aren't allowed.",
    ReasonCode.NOT_ALLOWED_VALUE: "That value isn't one of the allowed options.",
}


def _describe_pydantic_error(
    error_type: str, ctx: Mapping[str, object]
) -> tuple[ReasonCode, str, str | None]:
    reason = _PYDANTIC_TYPE_REASONS.get(error_type, ReasonCode.INVALID_CHARACTERS)
    message = _PYDANTIC_TYPE_MESSAGES.get(reason, "That value isn't valid.")
    rule: str | None = None
    if reason is ReasonCode.TOO_SHORT and "min_length" in ctx:
        rule = f"Use at least {ctx['min_length']} characters."
    elif reason is ReasonCode.TOO_LONG and "max_length" in ctx:
        rule = f"Use {ctx['max_length']} characters or fewer."
    return reason, message, rule


def _dotted_field_name(loc: tuple[object, ...]) -> str:
    parts = [str(part) for part in loc]
    if parts and parts[0] == "body":
        parts = parts[1:]
    return ".".join(parts)


def _looks_like_directory_field(field: str) -> bool:
    return field == "directory_name" or field.endswith(".directory_name")


def _narrow_ctx(value: object) -> Mapping[str, object]:
    """Narrow pydantic's untyped ``ctx`` into a plain mapping for lookups."""
    return value if isinstance(value, Mapping) else {}


def field_errors_from_request_validation(exc: RequestValidationError) -> list[FieldError]:
    """Translate a FastAPI ``RequestValidationError`` into contract-shaped field errors."""
    fields: list[FieldError] = []
    for raw_error in exc.errors():
        field_name = _dotted_field_name(raw_error.get("loc", ()))
        error_type = str(raw_error.get("type", ""))
        ctx = _narrow_ctx(raw_error.get("ctx"))
        reason, message, rule = _describe_pydantic_error(error_type, ctx)
        field_error = FieldError(
            field=field_name, reason=reason, message=message, rule=rule, suggestion=None
        )
        if _looks_like_directory_field(field_name):
            raw_input = raw_error.get("input")
            enriched = describe_directory_name(raw_input if isinstance(raw_input, str) else "")
            if enriched is not None:
                field_error = enriched.model_copy(update={"field": field_name})
        fields.append(field_error)
    return fields
