"""PaperMC build catalog and active-jar matching helpers.

Paper's Fill service publishes the server download and its SHA-256 together in
the build record.  The catalog is deliberately parsed strictly: a malformed
record is an error instead of an invitation to guess a filename or download
an unverified artifact.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import __version__

PAPER_BUILDS = "https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"
USER_AGENT = f"blockstead/{__version__} (https://github.com/LordMalachi/blockstead)"


class PaperBuildError(ValueError):
    """The Paper build endpoint failed or returned an unusable record."""


@dataclass(frozen=True, slots=True)
class PaperBuild:
    """The verified server download metadata for one Paper build."""

    id: int
    channel: str
    url: str
    file_name: str
    sha256: str


def _invalid_catalog() -> PaperBuildError:
    return PaperBuildError("Paper's build list had an unexpected shape or checksum.")


def _parse_build(entry: object) -> PaperBuild:
    if not isinstance(entry, dict):
        raise _invalid_catalog()

    build_id = entry.get("id")
    if not isinstance(build_id, int) or isinstance(build_id, bool) or build_id <= 0:
        raise _invalid_catalog()

    channel = entry.get("channel")
    if not isinstance(channel, str) or not channel:
        raise _invalid_catalog()

    downloads = entry.get("downloads")
    server = downloads.get("server:default") if isinstance(downloads, dict) else None
    if not isinstance(server, dict):
        raise _invalid_catalog()

    url = server.get("url")
    file_name = server.get("name")
    checksums = server.get("checksums")
    checksum = checksums.get("sha256") if isinstance(checksums, dict) else None
    parsed_url = urlparse(url) if isinstance(url, str) else None
    if (
        not isinstance(url, str)
        or parsed_url is None
        or parsed_url.scheme != "https"
        or not parsed_url.netloc
        or not isinstance(file_name, str)
        or not file_name
        or "/" in file_name
        or "\\" in file_name
        or not file_name.endswith(".jar")
        or not isinstance(checksum, str)
        or len(checksum) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in checksum)
    ):
        raise _invalid_catalog()

    return PaperBuild(
        id=build_id,
        channel=channel,
        url=url,
        file_name=file_name,
        sha256=checksum.lower(),
    )


async def list_paper_builds(
    client: httpx.AsyncClient, minecraft_version: str
) -> tuple[PaperBuild, ...]:
    """Fetch and strictly validate Paper builds for one Minecraft version."""
    if (
        not isinstance(minecraft_version, str)
        or not minecraft_version
        or any(
            character not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ._-"
            for character in minecraft_version
        )
    ):
        raise PaperBuildError("Paper was given an invalid Minecraft version.")
    try:
        response = await client.get(
            PAPER_BUILDS.format(version=minecraft_version),
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise PaperBuildError(
            f"Paper's build service did not answer as expected ({type(exc).__name__})."
        ) from exc

    if not isinstance(payload, list):
        raise _invalid_catalog()

    builds = tuple(_parse_build(entry) for entry in payload)
    if len({build.id for build in builds}) != len(builds):
        raise _invalid_catalog()
    return builds


def latest_stable_build(builds: tuple[PaperBuild, ...]) -> PaperBuild | None:
    """Return the highest-ID stable build, or ``None`` when none is listed."""
    stable = [build for build in builds if build.channel == "STABLE"]
    return max(stable, key=lambda build: build.id) if stable else None


def match_paper_build(path: Path, builds: tuple[PaperBuild, ...]) -> PaperBuild | None:
    """Match an active jar to a catalog record by its SHA-256 digest.

    The filename is intentionally ignored.  A downloaded or renamed active
    jar is identified only by the digest published by PaperMC.  Ambiguous
    catalog matches are rejected rather than selecting one build arbitrarily.
    """
    try:
        if not path.is_file():
            return None
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
    except OSError:
        return None
    matches = [build for build in builds if build.sha256.casefold() == value]
    return matches[0] if len(matches) == 1 else None


__all__ = [
    "PAPER_BUILDS",
    "PaperBuild",
    "PaperBuildError",
    "latest_stable_build",
    "list_paper_builds",
    "match_paper_build",
]
