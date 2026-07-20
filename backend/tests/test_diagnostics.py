import logging
from pathlib import Path

from blockstead.diagnostics import (
    BUFFER_HANDLER_NAME,
    FILE_HANDLER_NAME,
    DiagnosticLogBuffer,
    attach_logging,
    redact,
)


def test_redact_hides_home_directory_account_names() -> None:
    assert redact("scan failed for /home/alice/minecraft/world") == (
        "scan failed for /home/[account]/minecraft/world"
    )
    assert redact("/Users/derek/Documents/server") == "/Users/[account]/Documents/server"
    assert redact("moved /home/alice/a to /home/bob/b") == (
        "moved /home/[account]/a to /home/[account]/b"
    )


def test_redact_leaves_other_text_alone() -> None:
    assert redact("/var/lib/blockstead/backups kept 3 archives") == (
        "/var/lib/blockstead/backups kept 3 archives"
    )


def test_buffer_keeps_only_the_most_recent_records() -> None:
    buffer = DiagnosticLogBuffer(limit=3)
    logger = logging.getLogger("blockstead.test_buffer_limit")
    logger.addHandler(buffer)
    try:
        for index in range(5):
            logger.warning("event %d", index)
    finally:
        logger.removeHandler(buffer)
    messages = [entry["message"] for entry in buffer.tail(10)]
    assert messages == ["event 2", "event 3", "event 4"]


def test_buffer_tail_filters_by_level_and_captures_tracebacks() -> None:
    buffer = DiagnosticLogBuffer()
    logger = logging.getLogger("blockstead.test_buffer_levels")
    logger.addHandler(buffer)
    try:
        logger.info("routine note")
        try:
            raise RuntimeError("the disk under /home/alice vanished")
        except RuntimeError:
            logger.exception("backup failed")
    finally:
        logger.removeHandler(buffer)
    errors = buffer.tail(10, logging.WARNING)
    assert len(errors) == 1
    assert errors[0]["level"] == "ERROR"
    message = str(errors[0]["message"])
    assert "backup failed" in message
    assert "RuntimeError" in message
    assert "/home/[account]" in message
    assert "/home/alice" not in message
    assert len(buffer.tail(10, logging.INFO)) == 2


def test_attach_logging_replaces_handlers_and_writes_the_log_file(tmp_path: Path) -> None:
    attach_logging(tmp_path)
    buffer = attach_logging(tmp_path)
    logger = logging.getLogger("blockstead")
    names = [handler.get_name() for handler in logger.handlers]
    assert names.count(BUFFER_HANDLER_NAME) == 1
    assert names.count(FILE_HANDLER_NAME) == 1

    logging.getLogger("blockstead.test_attach").info("hello from the test")
    assert [entry["message"] for entry in buffer.tail(5)] == ["hello from the test"]
    content = (tmp_path / "logs" / "blockstead.log").read_text(encoding="utf-8")
    assert "hello from the test" in content
