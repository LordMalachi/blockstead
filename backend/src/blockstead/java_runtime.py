"""Discover installed Java runtimes and check profile prerequisites.

Probing runs each candidate executable with an argument array only
(never a shell) and reads a bounded amount of version output.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

_VERSION_PATTERN = re.compile(r'version "([0-9][0-9._]*)"')
_PROBE_TIMEOUT_SECONDS = 10
_MAX_OUTPUT_BYTES = 65536


class JavaRuntime(BaseModel):
    path: str
    version: str
    major: int


def _candidate_executables() -> list[Path]:
    candidates: list[Path] = []
    found = shutil.which("java")
    if found:
        candidates.append(Path(found))
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.append(Path(java_home) / "bin" / "java")
    for pattern_root, glob in (
        (Path("/usr/lib/jvm"), "*/bin/java"),
        (Path("/Library/Java/JavaVirtualMachines"), "*/Contents/Home/bin/java"),
    ):
        if pattern_root.is_dir():
            candidates.extend(sorted(pattern_root.glob(glob)))
    unique: dict[Path, Path] = {}
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved not in unique and os.access(resolved, os.X_OK):
            unique[resolved] = candidate
    return list(unique.values())


def _parse_major(version: str) -> int | None:
    parts = version.replace("_", ".").split(".")
    try:
        first = int(parts[0])
        return int(parts[1]) if first == 1 and len(parts) > 1 else first
    except (ValueError, IndexError):
        return None


def _probe(executable: Path) -> JavaRuntime | None:
    try:
        result = subprocess.run(  # noqa: S603
            [str(executable), "-version"],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (result.stderr + result.stdout)[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    match = _VERSION_PATTERN.search(output)
    if match is None:
        return None
    major = _parse_major(match.group(1))
    if major is None:
        return None
    return JavaRuntime(path=str(executable), version=match.group(1), major=major)


def discover_java_runtimes() -> list[JavaRuntime]:
    runtimes = [runtime for runtime in map(_probe, _candidate_executables()) if runtime]
    return sorted(runtimes, key=lambda runtime: runtime.major)


def find_java(required_major: int | None, runtimes: list[JavaRuntime]) -> JavaRuntime | None:
    """Pick the lowest runtime that satisfies the minimum requirement."""
    if required_major is None:
        return runtimes[-1] if runtimes else None
    for runtime in runtimes:
        if runtime.major >= required_major:
            return runtime
    return None
