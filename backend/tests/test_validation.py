"""Unit tests for blockstead.validation, per docs/validation-contract.md."""

import json

import pytest

from blockstead.app import error
from blockstead.validation import (
    DIRECTORY_PATTERN,
    FieldError,
    ReasonCode,
    describe_directory_name,
    normalize_server_directory_name,
    suggest_available_directory_name,
)

# The contract doc's worked example table (docs/validation-contract.md, "Sanitization must
# agree on both sides"). Every pair here must also be asserted by the frontend's own test
# for normalizeServerDirectoryName (frontend/src/lib/server-directory.test.ts).
#
# NOTE: the doc's table lists `"Ünïcødé"` -> `"nc-d"`. Applying the doc's own stated rule
# (trim, lowercase, replace every run of disallowed characters with a single "-", collapse
# repeated separators, strip leading/trailing non-alphanumerics) to that input yields
# "n-c-d", not "nc-d": lowering "Ünïcødé" gives "ünïcødé", the four accented characters
# (ü, ï, ø, é) are each a disallowed one-character run replaced by "-", giving
# "-n-c-d-", and stripping the leading and trailing "-" leaves "n-c-d" with no adjacent
# separators left to collapse. "nc-d" is not reachable from the written rule without an
# unwritten, additional step. This is flagged in the implementation report as a likely
# transcription error in the contract doc; "n-c-d" is asserted below as the correct
# output of the rule as written.
SANITIZER_TABLE: list[tuple[str, str]] = [
    ("  Family Server  ", "family-server"),
    ("My__Server!!", "my_server"),
    ("---", "minecraft-server"),
    ("Ünïcødé", "n-c-d"),
    ("A" * 80, "a" * 64),
]


@pytest.mark.parametrize("value,expected", SANITIZER_TABLE)
def test_normalize_server_directory_name_table(value: str, expected: str) -> None:
    assert normalize_server_directory_name(value) == expected


def test_normalize_server_directory_name_truncates_to_64_ending_alphanumeric() -> None:
    result = normalize_server_directory_name("A" * 80)
    assert len(result) == 64
    assert result[-1].isalnum()


def test_normalize_server_directory_name_empty_falls_back() -> None:
    assert normalize_server_directory_name("") == "minecraft-server"
    assert normalize_server_directory_name("   ") == "minecraft-server"
    assert normalize_server_directory_name("!!!") == "minecraft-server"


def test_normalize_server_directory_name_custom_fallback() -> None:
    assert normalize_server_directory_name("!!!", fallback="family-server") == "family-server"


def test_normalize_server_directory_name_output_always_matches_pattern() -> None:
    samples = [
        "  Family Server  ",
        "My__Server!!",
        "---",
        "Ünïcødé",
        "A" * 80,
        "",
        "already-fine",
        "123",
        "_leading_underscore",
        "trailing-",
        "a" * 200,
    ]
    for sample in samples:
        result = normalize_server_directory_name(sample)
        assert DIRECTORY_PATTERN.match(result), f"{sample!r} -> {result!r} is not pattern-valid"


def test_describe_directory_name_valid_returns_none() -> None:
    assert describe_directory_name("family-server") is None
    assert describe_directory_name("a") is None
    assert describe_directory_name("server_2") is None


def test_describe_directory_name_required_for_empty() -> None:
    result = describe_directory_name("")
    assert result is not None
    assert result.reason == ReasonCode.REQUIRED
    assert result.field == "directory_name"
    assert result.rule
    assert result.suggestion == "minecraft-server"


def test_describe_directory_name_too_long() -> None:
    result = describe_directory_name("a" * 65)
    assert result is not None
    assert result.reason == ReasonCode.TOO_LONG
    assert result.suggestion is not None
    assert len(result.suggestion) <= 64


def test_describe_directory_name_uppercase_not_allowed() -> None:
    result = describe_directory_name("Family-Server")
    assert result is not None
    assert result.reason == ReasonCode.UPPERCASE_NOT_ALLOWED
    assert result.suggestion == "family-server"


def test_describe_directory_name_must_start_with_letter_or_number() -> None:
    result = describe_directory_name("-family-server")
    assert result is not None
    assert result.reason == ReasonCode.MUST_START_WITH_LETTER_OR_NUMBER
    assert result.suggestion == "family-server"


def test_describe_directory_name_must_end_with_letter_or_number() -> None:
    result = describe_directory_name("family-server-")
    assert result is not None
    assert result.reason == ReasonCode.MUST_END_WITH_LETTER_OR_NUMBER
    assert result.suggestion == "family-server"


def test_describe_directory_name_invalid_characters() -> None:
    result = describe_directory_name("family server!")
    assert result is not None
    assert result.reason == ReasonCode.INVALID_CHARACTERS
    assert result.suggestion == "family-server"


def test_describe_directory_name_suggestion_always_passes_validation() -> None:
    for sample in ["", "A" * 90, "Family-Server", "-lead", "trail-", "bad name!"]:
        result = describe_directory_name(sample)
        assert result is not None
        assert result.suggestion is not None
        assert DIRECTORY_PATTERN.match(result.suggestion)


def test_suggest_available_directory_name_returns_base_when_free() -> None:
    assert suggest_available_directory_name("family-server", lambda name: False) == "family-server"


def test_suggest_available_directory_name_increments_suffix() -> None:
    taken = {"family-server", "family-server-2", "family-server-3"}
    result = suggest_available_directory_name("family-server", lambda name: name in taken)
    assert result == "family-server-4"


def test_suggest_available_directory_name_normalizes_base_first() -> None:
    result = suggest_available_directory_name("Family Server!", lambda name: False)
    assert result == "family-server"


def test_suggest_available_directory_name_result_always_matches_pattern() -> None:
    taken = {f"a-{n}" if n > 1 else "a" for n in range(1, 50)}
    result = suggest_available_directory_name("a", lambda name: name in taken)
    assert DIRECTORY_PATTERN.match(result)
    assert result not in taken


def test_field_error_serializes_reason_as_plain_string() -> None:
    field_error = FieldError(
        field="directory_name",
        reason=ReasonCode.INVALID_CHARACTERS,
        message="Use only lowercase letters, numbers, hyphens and underscores.",
        rule="Start with a lowercase letter or number.",
        suggestion="family-server",
    )
    dumped = field_error.model_dump(mode="json")
    assert dumped["reason"] == "INVALID_CHARACTERS"
    assert isinstance(dumped["reason"], str)


def test_error_helper_omits_fields_key_when_absent() -> None:
    response = error(400, "REQUEST_FAILED", "Something went wrong.")
    body = response.body
    assert b'"fields"' not in body


def test_error_helper_includes_fields_when_present() -> None:
    field_error = FieldError(
        field="directory_name",
        reason=ReasonCode.REQUIRED,
        message="A server folder name is required.",
        rule="Use 1 to 64 characters.",
        suggestion="minecraft-server",
    )
    response = error(
        422, "REQUEST_INVALID", "Some submitted information was invalid.", fields=[field_error]
    )
    body = json.loads(response.body)
    assert body["error"]["fields"] == [
        {
            "field": "directory_name",
            "reason": "REQUIRED",
            "message": "A server folder name is required.",
            "rule": "Use 1 to 64 characters.",
            "suggestion": "minecraft-server",
        }
    ]
