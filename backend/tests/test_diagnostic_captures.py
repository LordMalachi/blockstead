from pathlib import Path

import pytest

from blockstead.diagnostic_captures import (
    DiagnosticCaptureError,
    resolve_capture_path,
    write_transcript,
)


def test_write_transcript_persists_content_and_returns_relative_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"

    relative, size = write_transcript(data_dir, "profile-1", "capture-1", "console output\n")

    assert relative == "diagnostic-captures/profile-1/capture-1.txt"
    target = data_dir / relative
    assert target.read_text(encoding="utf-8") == "console output\n"
    assert size == len(b"console output\n")


def test_write_transcript_leaves_the_capture_directory_listable(tmp_path: Path) -> None:
    """The write-and-harden path (mkdir + restrict_to_owner + atomic write)
    must never lock the owner out of the profile's capture directory."""

    data_dir = tmp_path / "data"

    write_transcript(data_dir, "profile-1", "capture-1", "evidence")

    capture_dir = data_dir / "diagnostic-captures" / "profile-1"
    names = [entry.name for entry in capture_dir.iterdir()]
    assert "capture-1.txt" in names
    probe = capture_dir / "probe.txt"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def test_write_transcript_rejects_unsafe_identifiers(tmp_path: Path) -> None:
    with pytest.raises(DiagnosticCaptureError):
        write_transcript(tmp_path / "data", "../escape", "capture-1", "x")


def test_resolve_capture_path_accepts_a_written_transcript(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    relative, _ = write_transcript(data_dir, "profile-1", "capture-1", "evidence")

    resolved = resolve_capture_path(data_dir, "profile-1", relative)

    assert resolved == (data_dir / relative).resolve()


def test_resolve_capture_path_rejects_traversal_outside_private_storage(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    write_transcript(data_dir, "profile-1", "capture-1", "evidence")

    with pytest.raises(DiagnosticCaptureError):
        resolve_capture_path(data_dir, "profile-1", "../../outside.txt")
