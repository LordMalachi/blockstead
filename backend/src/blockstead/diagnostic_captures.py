"""Private, owner-exportable diagnostic capture transcripts."""

from pathlib import Path


class DiagnosticCaptureError(RuntimeError):
    """A diagnostic capture could not be safely retained for its owner."""


def capture_path(data_directory: Path, profile_id: str, capture_id: str) -> Path:
    """Return a generated private path without accepting a browser filename."""

    if not profile_id or not capture_id or "/" in profile_id or "/" in capture_id:
        raise DiagnosticCaptureError("The diagnostic capture identity is invalid.")
    return data_directory / "diagnostic-captures" / profile_id / f"{capture_id}.txt"


def write_transcript(
    data_directory: Path,
    profile_id: str,
    capture_id: str,
    content: str,
) -> tuple[str, int]:
    """Persist bounded console evidence locally until the owner downloads it."""

    target = capture_path(data_directory, profile_id, capture_id)
    data = content.encode("utf-8", errors="replace")
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.parent.chmod(0o700)
        target.write_bytes(data)
        target.chmod(0o600)
    except OSError as exc:
        raise DiagnosticCaptureError("Blockstead could not retain the diagnostic capture.") from exc
    return target.relative_to(data_directory).as_posix(), len(data)


def resolve_capture_path(data_directory: Path, profile_id: str, output_file: str) -> Path:
    """Resolve a generated capture file only when it remains below private storage."""

    try:
        root = data_directory.resolve(strict=True)
        expected_parent = (root / "diagnostic-captures" / profile_id).resolve(strict=True)
        target = (root / output_file).resolve(strict=True)
        target.relative_to(expected_parent)
        if not target.is_file() or target.is_symlink() or target.suffix != ".txt":
            raise OSError
        return target
    except (OSError, ValueError) as exc:
        raise DiagnosticCaptureError(
            "This diagnostic capture is no longer available locally."
        ) from exc
