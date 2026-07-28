"""Durable, expiring review records for owner-supplied extension jars."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

REVIEW_TTL_SECONDS = 60 * 60
MAX_IMPORT_FILES = 20


class ManualImportApplyRequest(BaseModel):
    review_id: str = Field(pattern=r"^[0-9a-f]{16}$")
    acknowledge_unknown: bool = False


def manifest_path(staging: Path) -> Path:
    return staging / ".blockstead-manual-review.json"


def save_manifest(staging: Path, payload: dict[str, Any]) -> None:
    manifest_path(staging).write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )


def load_manifest(staging: Path) -> dict[str, Any]:
    path = manifest_path(staging)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("That manual import review is no longer available.") from exc
    if not isinstance(payload, dict):
        raise ValueError("That manual import review is no longer available.")
    created_at = payload.get("created_at")
    if not isinstance(created_at, int | float) or time.time() - created_at > REVIEW_TTL_SECONDS:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError("That manual import review expired. Choose the jar files again.")
    return payload


def cleanup_expired(extension_directory: Path) -> None:
    if not extension_directory.is_dir() or extension_directory.is_symlink():
        return
    now = time.time()
    for candidate in extension_directory.glob(".blockstead-manual-*"):
        try:
            expired = (
                candidate.is_dir()
                and not candidate.is_symlink()
                and now - candidate.stat().st_mtime > REVIEW_TTL_SECONDS
            )
        except OSError:
            continue
        if expired:
            shutil.rmtree(candidate, ignore_errors=True)
