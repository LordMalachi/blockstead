"""Provision new server profiles from official download sources.

This module downloads data only. It never executes anything it
downloads, never writes eula.txt, and always stages a download and
verifies its published checksum before the file reaches its final name.
"""

import hashlib
import re
from pathlib import Path

import httpx
from pydantic import BaseModel

USER_AGENT = "blockstead/0.1.0 (https://github.com/LordMalachi/blockstead)"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DIRECTORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_PROJECT = "https://fill.papermc.io/v3/projects/paper"
PAPER_BUILDS = "https://fill.papermc.io/v3/projects/paper/versions/{version}/builds"
FABRIC_GAME = "https://meta.fabricmc.net/v2/versions/game"
FABRIC_LOADER = "https://meta.fabricmc.net/v2/versions/loader/{version}"
FABRIC_INSTALLER = "https://meta.fabricmc.net/v2/versions/installer"
FABRIC_SERVER_JAR = (
    "https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installer}/server/jar"
)


class ProvisionError(ValueError):
    """The requested profile cannot be provisioned; message is user-safe."""


class ProvisionPlan(BaseModel):
    distribution: str
    minecraft_version: str
    file_name: str
    url: str
    checksum_algorithm: str | None
    checksum: str | None
    notes: list[str]


class ProvisionResult(BaseModel):
    plan: ProvisionPlan
    directory: str
    sha256: str


async def _get_json(client: httpx.AsyncClient, url: str) -> object:
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProvisionError(
            f"A download source did not answer as expected ({type(exc).__name__})."
        ) from exc


def _string_versions(value: object) -> list[str]:
    """Tolerantly flatten a version listing into plain version strings."""
    items: list[object] = []
    if isinstance(value, dict):
        for entry in value.values():
            items.extend(entry if isinstance(entry, list) else [entry])
    elif isinstance(value, list):
        items = list(value)
    versions: list[str] = []
    for item in items:
        if isinstance(item, str):
            versions.append(item)
        elif isinstance(item, dict):
            candidate = item.get("version") or item.get("id")
            versions.append(candidate) if isinstance(candidate, str) else None
    return versions


async def list_versions(client: httpx.AsyncClient, distribution: str) -> list[str]:
    if distribution == "vanilla":
        manifest = await _get_json(client, MOJANG_MANIFEST)
        if not isinstance(manifest, dict):
            raise ProvisionError("Mojang's version list had an unexpected shape.")
        return [
            entry["id"]
            for entry in manifest.get("versions", [])
            if isinstance(entry, dict) and entry.get("type") == "release"
        ]
    if distribution == "paper":
        project = await _get_json(client, PAPER_PROJECT)
        if not isinstance(project, dict):
            raise ProvisionError("Paper's version list had an unexpected shape.")
        return _string_versions(project.get("versions"))
    if distribution == "fabric":
        games = await _get_json(client, FABRIC_GAME)
        if not isinstance(games, list):
            raise ProvisionError("Fabric's version list had an unexpected shape.")
        return [
            entry["version"]
            for entry in games
            if isinstance(entry, dict) and entry.get("stable") and "version" in entry
        ]
    raise ProvisionError("Blockstead cannot list downloadable versions for this distribution.")


async def _vanilla_plan(client: httpx.AsyncClient, version: str) -> ProvisionPlan:
    manifest = await _get_json(client, MOJANG_MANIFEST)
    entries = manifest.get("versions", []) if isinstance(manifest, dict) else []
    detail_url = next(
        (
            entry.get("url")
            for entry in entries
            if isinstance(entry, dict) and entry.get("id") == version
        ),
        None,
    )
    if not isinstance(detail_url, str):
        raise ProvisionError(f"Mojang does not list a Minecraft version named {version}.")
    detail = await _get_json(client, detail_url)
    server = detail.get("downloads", {}).get("server") if isinstance(detail, dict) else None
    if not isinstance(server, dict) or not isinstance(server.get("url"), str):
        raise ProvisionError(f"Minecraft {version} has no downloadable server file.")
    return ProvisionPlan(
        distribution="vanilla",
        minecraft_version=version,
        file_name="server.jar",
        url=server["url"],
        checksum_algorithm="sha1",
        checksum=server.get("sha1") if isinstance(server.get("sha1"), str) else None,
        notes=["Downloaded from Mojang and verified against its published SHA-1."],
    )


async def _paper_plan(client: httpx.AsyncClient, version: str) -> ProvisionPlan:
    builds = await _get_json(client, PAPER_BUILDS.format(version=version))
    if not isinstance(builds, list) or not builds:
        raise ProvisionError(f"Paper does not list builds for Minecraft {version}.")
    usable = [entry for entry in builds if isinstance(entry, dict)]
    stable = [entry for entry in usable if entry.get("channel") == "STABLE"]
    chosen = max(stable or usable, key=lambda entry: entry.get("id", 0))
    download = chosen.get("downloads", {}).get("server:default")
    if not isinstance(download, dict) or not isinstance(download.get("url"), str):
        raise ProvisionError(f"Paper build data for {version} had an unexpected shape.")
    checksums = download.get("checksums", {})
    sha256 = checksums.get("sha256") if isinstance(checksums, dict) else None
    name = download.get("name")
    return ProvisionPlan(
        distribution="paper",
        minecraft_version=version,
        file_name=name if isinstance(name, str) else f"paper-{version}.jar",
        url=download["url"],
        checksum_algorithm="sha256" if isinstance(sha256, str) else None,
        checksum=sha256 if isinstance(sha256, str) else None,
        notes=[f"Paper build {chosen.get('id')} from the official PaperMC download service."],
    )


def _first_stable_version(entries: object) -> str | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        record = entry["loader"] if isinstance(entry.get("loader"), dict) else entry
        if record.get("stable") and isinstance(record.get("version"), str):
            return str(record["version"])
    return None


async def _fabric_plan(client: httpx.AsyncClient, version: str) -> ProvisionPlan:
    loader = _first_stable_version(await _get_json(client, FABRIC_LOADER.format(version=version)))
    installer = _first_stable_version(await _get_json(client, FABRIC_INSTALLER))
    if loader is None or installer is None:
        raise ProvisionError(f"Fabric does not offer a stable server for Minecraft {version}.")
    return ProvisionPlan(
        distribution="fabric",
        minecraft_version=version,
        file_name=f"fabric-server-mc.{version}-loader.{loader}-launcher.{installer}.jar",
        url=FABRIC_SERVER_JAR.format(version=version, loader=loader, installer=installer),
        checksum_algorithm=None,
        checksum=None,
        notes=[
            f"Fabric loader {loader} with installer {installer}.",
            "Fabric does not publish a checksum for this launcher; it was downloaded "
            "over TLS from meta.fabricmc.net and its SHA-256 was recorded.",
        ],
    )


async def resolve_plan(client: httpx.AsyncClient, distribution: str, version: str) -> ProvisionPlan:
    if distribution == "vanilla":
        return await _vanilla_plan(client, version)
    if distribution == "paper":
        return await _paper_plan(client, version)
    if distribution == "fabric":
        return await _fabric_plan(client, version)
    if distribution == "neoforge":
        raise ProvisionError(
            "Blockstead does not download NeoForge yet because its installer must be "
            "executed. Run the official NeoForge installer in a folder inside the "
            "server root, then import that folder."
        )
    raise ProvisionError("Blockstead cannot provision this distribution.")


async def _download_verified(
    client: httpx.AsyncClient, plan: ProvisionPlan, directory: Path
) -> str:
    staging = directory / f".{plan.file_name}.part"
    published = hashlib.new(plan.checksum_algorithm) if plan.checksum_algorithm else None
    recorded = hashlib.sha256()
    received = 0
    try:
        async with client.stream("GET", plan.url) as response:
            response.raise_for_status()
            with staging.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > MAX_DOWNLOAD_BYTES:
                        raise ProvisionError("The download exceeded the allowed size limit.")
                    if published is not None:
                        published.update(chunk)
                    recorded.update(chunk)
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        staging.unlink(missing_ok=True)
        raise ProvisionError(
            f"The download failed before it completed ({type(exc).__name__})."
        ) from exc
    except ProvisionError:
        staging.unlink(missing_ok=True)
        raise
    if published is not None and plan.checksum and published.hexdigest() != plan.checksum:
        staging.unlink(missing_ok=True)
        raise ProvisionError(
            "The downloaded file did not match its published checksum and was discarded."
        )
    staging.replace(directory / plan.file_name)
    return recorded.hexdigest()


async def provision_profile(
    client: httpx.AsyncClient,
    server_root: Path,
    directory_name: str,
    distribution: str,
    version: str,
) -> ProvisionResult:
    """Create a new profile folder and place a verified server file in it."""
    if not DIRECTORY_PATTERN.match(directory_name):
        raise ProvisionError(
            "Folder names use lowercase letters, digits, hyphens, and underscores."
        )
    root = server_root.resolve(strict=True)
    target = root / directory_name
    if target.exists():
        raise ProvisionError("A folder with that name already exists in the server root.")
    plan = await resolve_plan(client, distribution, version)
    target.mkdir(mode=0o755)
    try:
        sha256 = await _download_verified(client, plan, target)
    except ProvisionError:
        try:
            target.rmdir()
        except OSError:
            pass
        raise
    return ProvisionResult(plan=plan, directory=str(target), sha256=sha256)
