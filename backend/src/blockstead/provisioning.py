"""Provision new server profiles from official download sources.

Downloads are staged and checksum-verified where publishers provide a
digest. Forge, Quilt, and NeoForge require their official Java installer;
those installers run without a shell, with a timeout, and only inside the
new profile directory. This module never writes or accepts eula.txt.
"""

import asyncio
import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import httpx
from pydantic import BaseModel

from . import __version__, paper_builds
from .distributions import LaunchPlanError, launch_arguments
from .host_fs import rmtree
from .paper_builds import (
    PaperBuildError,
    latest_stable_build,
    list_paper_builds,
)

USER_AGENT = f"blockstead/{__version__} (https://github.com/LordMalachi/blockstead)"
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DIRECTORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
PAPER_PROJECT = "https://fill.papermc.io/v3/projects/paper"
PAPER_BUILDS = paper_builds.PAPER_BUILDS
FABRIC_GAME = "https://meta.fabricmc.net/v2/versions/game"
FABRIC_LOADER = "https://meta.fabricmc.net/v2/versions/loader/{version}"
FABRIC_INSTALLER = "https://meta.fabricmc.net/v2/versions/installer"
FABRIC_SERVER_JAR = (
    "https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installer}/server/jar"
)
FORGE_PROMOTIONS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEOFORGE_METADATA = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
QUILT_GAME = "https://meta.quiltmc.org/v3/versions/game"
QUILT_LOADER = "https://meta.quiltmc.org/v3/versions/loader/{version}"
QUILT_INSTALLER = "https://meta.quiltmc.org/v3/versions/installer"
QUILT_INSTALLER_MAVEN = (
    "https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/"
    "{installer}/quilt-installer-{installer}.jar"
)
INSTALL_TIMEOUT_SECONDS = 300


class ProvisionError(ValueError):
    """The requested profile cannot be provisioned; message is user-safe."""


@dataclass(frozen=True, slots=True)
class FabricLoader:
    """One loader record published by Fabric Meta for a Minecraft version."""

    version: str
    stable: bool


class ProvisionPlan(BaseModel):
    distribution: str
    minecraft_version: str
    loader_version: str | None = None
    file_name: str
    url: str
    checksum_algorithm: str | None
    checksum: str | None
    notes: list[str]
    paper_build: int | None = None


class ProvisionResult(BaseModel):
    plan: ProvisionPlan
    directory: str
    sha256: str


async def _get_json(client: httpx.AsyncClient, url: str) -> object:
    try:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProvisionError(
            f"A download source did not answer as expected ({type(exc).__name__})."
        ) from exc


async def _get_text(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
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
    if distribution == "forge":
        promotions = await _get_json(client, FORGE_PROMOTIONS)
        values = promotions.get("promos") if isinstance(promotions, dict) else None
        if not isinstance(values, dict):
            raise ProvisionError("Forge's version list had an unexpected shape.")
        forge_versions = {
            key.rsplit("-", 1)[0] for key in values if key.endswith(("-recommended", "-latest"))
        }
        return sorted(forge_versions, key=_version_key, reverse=True)
    if distribution == "neoforge":
        neoforge_versions = _maven_versions(await _get_text(client, NEOFORGE_METADATA))
        return sorted(
            {
                minecraft
                for item in neoforge_versions
                if (minecraft := _neoforge_minecraft(item)) != "unknown"
            },
            key=_version_key,
            reverse=True,
        )
    if distribution == "quilt":
        games = await _get_json(client, QUILT_GAME)
        if not isinstance(games, list):
            raise ProvisionError("Quilt's version list had an unexpected shape.")
        return [
            entry["version"]
            for entry in games
            if isinstance(entry, dict)
            and entry.get("stable")
            and isinstance(entry.get("version"), str)
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


async def _paper_plan(
    client: httpx.AsyncClient, version: str, paper_build: int | None = None
) -> ProvisionPlan:
    try:
        builds = await list_paper_builds(client, version)
    except PaperBuildError as exc:
        raise ProvisionError(str(exc)) from exc

    if paper_build is None:
        chosen = latest_stable_build(builds)
        if chosen is None:
            raise ProvisionError(f"Paper does not offer a stable build for Minecraft {version}.")
    else:
        chosen = next(
            (build for build in builds if build.id == paper_build and build.channel == "STABLE"),
            None,
        )
        if chosen is None:
            raise ProvisionError(
                f"Paper does not offer stable build {paper_build} for Minecraft {version}."
            )

    return ProvisionPlan(
        distribution="paper",
        minecraft_version=version,
        file_name=chosen.file_name,
        url=chosen.url,
        checksum_algorithm="sha256",
        checksum=chosen.sha256,
        notes=[f"Paper build {chosen.id} from the official PaperMC download service."],
        paper_build=chosen.id,
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


async def list_fabric_loaders(
    client: httpx.AsyncClient, minecraft_version: str
) -> tuple[FabricLoader, ...]:
    """Fetch and strictly validate Fabric loader records for one game version."""
    if not isinstance(minecraft_version, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", minecraft_version
    ):
        raise ProvisionError("Fabric was given an invalid Minecraft version.")
    payload = await _get_json(client, FABRIC_LOADER.format(version=minecraft_version))
    if not isinstance(payload, list):
        raise ProvisionError("Fabric's loader version list had an unexpected shape.")

    records: list[FabricLoader] = []
    for entry in payload:
        record = entry.get("loader") if isinstance(entry, dict) else None
        if not isinstance(record, dict):
            raise ProvisionError("Fabric's loader version list had an unexpected shape.")
        loader = record.get("version")
        stable = record.get("stable")
        if (
            not isinstance(loader, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}", loader)
            or not isinstance(stable, bool)
        ):
            raise ProvisionError("Fabric's loader version list had an unexpected shape.")
        records.append(FabricLoader(version=loader, stable=stable))
    if len({record.version for record in records}) != len(records):
        raise ProvisionError("Fabric's loader version list had duplicate versions.")
    return tuple(records)


async def list_fabric_stable_loaders(
    client: httpx.AsyncClient, minecraft_version: str
) -> tuple[str, ...]:
    """Return the stable Fabric loader versions listed for one game version."""
    catalog = await list_fabric_loaders(client, minecraft_version)
    return tuple(entry.version for entry in catalog if entry.stable)


def _version_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r"[.+_-]", value)
    )


def _maven_versions(raw: str) -> list[str]:
    try:
        root = ET.fromstring(raw)  # noqa: S314 - stdlib parser does not fetch external entities
    except ET.ParseError as exc:
        raise ProvisionError("A loader version list had an unexpected shape.") from exc
    return [node.text for node in root.findall("./versioning/versions/version") if node.text]


def _neoforge_minecraft(loader_version: str) -> str:
    parts = loader_version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        return "unknown"
    major, minor = int(parts[0]), int(parts[1])
    if major < 26:
        return f"1.{major}.{minor}"
    patch = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
    return f"{major}.{minor}.{patch}" if patch else f"{major}.{minor}"


async def fabric_plan(
    client: httpx.AsyncClient, version: str, loader_version: str | None = None
) -> ProvisionPlan:
    """Plan the Fabric server launcher, optionally pinning the loader version."""
    stable_loaders = await list_fabric_stable_loaders(client, version)
    if loader_version is None:
        if not stable_loaders:
            raise ProvisionError(f"Fabric does not offer a stable server for Minecraft {version}.")
        loader = max(stable_loaders, key=_version_key)
    else:
        if loader_version not in stable_loaders:
            raise ProvisionError(
                f"Fabric does not offer stable loader {loader_version} for Minecraft {version}."
            )
        loader = loader_version
    installer = _first_stable_version(await _get_json(client, FABRIC_INSTALLER))
    if installer is None:
        raise ProvisionError(f"Fabric does not offer a stable server for Minecraft {version}.")
    return ProvisionPlan(
        distribution="fabric",
        minecraft_version=version,
        loader_version=loader,
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


async def forge_plan(
    client: httpx.AsyncClient, version: str, loader_version: str | None = None
) -> ProvisionPlan:
    promotions = await _get_json(client, FORGE_PROMOTIONS)
    promos = promotions.get("promos") if isinstance(promotions, dict) else None
    if not isinstance(promos, dict):
        raise ProvisionError("Forge's version list had an unexpected shape.")
    loader = loader_version
    if loader is None:
        candidate = promos.get(f"{version}-recommended") or promos.get(f"{version}-latest")
        loader = candidate if isinstance(candidate, str) else None
    if loader is None:
        raise ProvisionError(f"Forge does not list a server installer for Minecraft {version}.")
    coordinate = loader if loader.startswith(f"{version}-") else f"{version}-{loader}"
    file_name = f"forge-{coordinate}-installer.jar"
    url = f"{FORGE_MAVEN}/{coordinate}/{file_name}"
    checksum = (await _get_text(client, f"{url}.sha1")).strip().split()[0]
    return ProvisionPlan(
        distribution="forge",
        minecraft_version=version,
        loader_version=coordinate.removeprefix(f"{version}-"),
        file_name=file_name,
        url=url,
        checksum_algorithm="sha1",
        checksum=checksum,
        notes=[
            f"Forge {coordinate} from the official Forge Maven repository.",
            "The verified official installer runs only inside the new server folder.",
        ],
    )


async def neoforge_plan(
    client: httpx.AsyncClient, version: str, loader_version: str | None = None
) -> ProvisionPlan:
    available = _maven_versions(await _get_text(client, NEOFORGE_METADATA))
    if loader_version:
        candidates = [item for item in available if item == loader_version]
    else:
        candidates = [item for item in available if _neoforge_minecraft(item) == version]
    if not candidates:
        raise ProvisionError(f"NeoForge does not list a server installer for Minecraft {version}.")
    stable = [item for item in candidates if not re.search(r"(?i)(alpha|beta|rc)", item)]
    loader = max(stable or candidates, key=_version_key)
    file_name = f"neoforge-{loader}-installer.jar"
    url = f"{NEOFORGE_MAVEN}/{loader}/{file_name}"
    checksum = (await _get_text(client, f"{url}.sha1")).strip().split()[0]
    return ProvisionPlan(
        distribution="neoforge",
        minecraft_version=version,
        loader_version=loader,
        file_name=file_name,
        url=url,
        checksum_algorithm="sha1",
        checksum=checksum,
        notes=[
            f"NeoForge {loader} from the official NeoForged Maven repository.",
            "The verified official installer runs only inside the new server folder.",
        ],
    )


async def quilt_plan(
    client: httpx.AsyncClient, version: str, loader_version: str | None = None
) -> ProvisionPlan:
    loaders = await _get_json(client, QUILT_LOADER.format(version=version))
    loader = loader_version or _first_stable_version(loaders)
    if loader is None and isinstance(loaders, list):
        choices = [
            entry.get("loader", entry).get("version")
            for entry in loaders
            if isinstance(entry, dict) and isinstance(entry.get("loader", entry), dict)
        ]
        stable_loaders = [
            item
            for item in choices
            if isinstance(item, str) and not re.search(r"(?i)(alpha|beta|rc)", item)
        ]
        loader = max(stable_loaders, key=_version_key) if stable_loaders else None
    installers = await _get_json(client, QUILT_INSTALLER)
    installer_entries = installers if isinstance(installers, list) else []
    installer = _first_stable_version(installers)
    if installer is None and isinstance(installers, list):
        installer = next(
            (
                entry.get("version")
                for entry in installers
                if isinstance(entry, dict) and isinstance(entry.get("version"), str)
            ),
            None,
        )
    if loader is None or installer is None:
        raise ProvisionError(f"Quilt does not offer a server for Minecraft {version}.")
    installer_record = next(
        (
            entry
            for entry in installer_entries
            if isinstance(entry, dict) and entry.get("version") == installer
        ),
        {},
    )
    listed_url = installer_record.get("url") if isinstance(installer_record, dict) else None
    url = (
        listed_url
        if isinstance(listed_url, str) and listed_url.startswith("https://")
        else QUILT_INSTALLER_MAVEN.format(installer=installer)
    )
    hashes = installer_record.get("hashes") if isinstance(installer_record, dict) else None
    published = hashes.get("sha512") if isinstance(hashes, dict) else None
    checksum: str | None = None
    checksum_algorithm: str | None = None
    if isinstance(published, str):
        checksum, checksum_algorithm = published, "sha512"
    else:
        try:
            checksum = (await _get_text(client, f"{url}.sha1")).strip().split()[0]
            checksum_algorithm = "sha1"
        except ProvisionError:
            pass
    return ProvisionPlan(
        distribution="quilt",
        minecraft_version=version,
        loader_version=loader,
        file_name=f"quilt-installer-{installer}.jar",
        url=url,
        checksum_algorithm=checksum_algorithm,
        checksum=checksum,
        notes=[
            f"Quilt Loader {loader} with installer {installer}.",
            "The official Quilt installer downloads the Minecraft server and creates its launcher.",
        ],
    )


async def resolve_plan(
    client: httpx.AsyncClient,
    distribution: str,
    version: str,
    loader_version: str | None = None,
    paper_build: int | None = None,
) -> ProvisionPlan:
    if distribution == "vanilla":
        return await _vanilla_plan(client, version)
    if distribution == "paper":
        return await _paper_plan(client, version, paper_build)
    if distribution == "fabric":
        return await fabric_plan(client, version, loader_version)
    if distribution == "forge":
        return await forge_plan(client, version, loader_version)
    if distribution == "quilt":
        return await quilt_plan(client, version, loader_version)
    if distribution == "neoforge":
        return await neoforge_plan(client, version, loader_version)
    raise ProvisionError("Blockstead cannot provision this distribution.")


async def download_verified_file(
    client: httpx.AsyncClient,
    url: str,
    directory: Path,
    file_name: str,
    checksum_algorithm: str | None,
    checksum: str | None,
) -> str:
    """Stream a download to a staging file, verify it, and place it atomically.

    Returns the SHA-256 of the received bytes for audit records.
    """
    staging = directory / f".{file_name}.part"
    try:
        published = hashlib.new(checksum_algorithm) if checksum_algorithm else None
    except ValueError as exc:
        raise ProvisionError("The download used an unsupported checksum algorithm.") from exc
    recorded = hashlib.sha256()
    received = 0

    def discard_staging() -> None:
        try:
            staging.unlink(missing_ok=True)
        except OSError:
            # The original download error is the useful result. A best-effort
            # cleanup failure must not turn it into an unhandled server error.
            pass

    try:
        # Catalog CDNs commonly redirect to a signed edge URL. Keep the
        # download helper correct even when a caller supplied a client whose
        # default does not follow redirects.
        async with client.stream("GET", url, follow_redirects=True) as response:
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
    except (httpx.HTTPError, OSError) as exc:
        discard_staging()
        raise ProvisionError(
            f"The download failed before it completed ({type(exc).__name__})."
        ) from exc
    except ProvisionError:
        discard_staging()
        raise
    if (
        published is not None
        and checksum
        and published.hexdigest().casefold() != checksum.casefold()
    ):
        discard_staging()
        raise ProvisionError(
            "The downloaded file did not match its published checksum and was discarded."
        )
    try:
        staging.replace(directory / file_name)
    except OSError as exc:
        discard_staging()
        raise ProvisionError("The downloaded file could not be placed safely.") from exc
    return recorded.hexdigest()


async def _download_verified(
    client: httpx.AsyncClient, plan: ProvisionPlan, directory: Path
) -> str:
    return await download_verified_file(
        client, plan.url, directory, plan.file_name, plan.checksum_algorithm, plan.checksum
    )


async def _run_installer(arguments: tuple[str, ...], directory: Path) -> None:
    """Run one verified loader installer in a new profile folder without a shell."""
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=directory,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=INSTALL_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise ProvisionError("The loader installer timed out and was stopped.") from exc
    except OSError as exc:
        raise ProvisionError("The Java loader installer could not be started.") from exc
    if process.returncode != 0:
        raise ProvisionError(f"The loader installer exited with code {process.returncode}.")


async def install_loader(
    client: httpx.AsyncClient,
    plan: ProvisionPlan,
    directory: Path,
    java_executable: str | None,
) -> str:
    """Download a server artifact and, where required, install its loader."""
    download_name = "fabric-server-launch.jar" if plan.distribution == "fabric" else plan.file_name
    sha256 = await download_verified_file(
        client,
        plan.url,
        directory,
        download_name,
        plan.checksum_algorithm,
        plan.checksum,
    )
    if plan.distribution in {"forge", "quilt", "neoforge"}:
        if java_executable is None:
            raise ProvisionError(
                f"Installing {plan.distribution.capitalize()} needs a compatible Java runtime."
            )
        installer = directory / download_name
        arguments: tuple[str, ...]
        if plan.distribution == "quilt":
            arguments = (
                java_executable,
                "-jar",
                str(installer),
                "install",
                "server",
                plan.minecraft_version,
                plan.loader_version or "",
                "--download-server",
                "--install-dir=.",
            )
        else:
            arguments = (java_executable, "-jar", str(installer), "--installServer")
        await _run_installer(arguments, directory)
        installer.unlink(missing_ok=True)
    try:
        launch_arguments(plan.distribution, directory, java_executable or "java")
    except LaunchPlanError as exc:
        raise ProvisionError(
            "The download completed, but the expected server launch files were not created."
        ) from exc
    return sha256


async def provision_profile(
    client: httpx.AsyncClient,
    server_root: Path,
    directory_name: str,
    distribution: str,
    version: str,
    loader_version: str | None = None,
    java_executable: str | None = None,
    paper_build: int | None = None,
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
    plan = await resolve_plan(client, distribution, version, loader_version, paper_build)
    target.mkdir(mode=0o755, parents=True)
    try:
        sha256 = await install_loader(client, plan, target, java_executable)
    except (ProvisionError, OSError):
        # A ProvisionError is raised regardless of whether this cleanup
        # succeeds; a leftover partial profile folder is orphaned disk
        # usage, not a mistaken "provisioned" report.
        try:
            rmtree(target)
        except OSError:
            pass
        raise
    return ProvisionResult(plan=plan, directory=str(target), sha256=sha256)
