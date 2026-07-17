"""Import Modrinth modpacks (.mrpack) as new loader-backed server profiles.

A .mrpack is a zip holding modrinth.index.json plus override folders.
Everything inside it is treated as untrusted data: file paths are
validated against traversal, download hosts are allowlisted per the
Modrinth pack specification, every download is checksum-verified, and
eula.txt is never written from pack contents. Packs that need a loader
installer-based loaders are provisioned through the same bounded official
installer path used by new profiles.
"""

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from .distributions import required_java_major
from .java_runtime import discover_java_runtimes, find_java
from .modrinth import (
    MODRINTH_API,
    ModrinthError,
    ModrinthProject,
    _best_version,
    _get_json,
    _version_by_id,
)
from .provisioning import (
    DIRECTORY_PATTERN,
    ProvisionError,
    download_verified_file,
    install_loader,
    resolve_plan,
)

MAX_MRPACK_BYTES = 256 * 1024 * 1024
MAX_PACK_FILES = 500
MAX_OVERRIDE_FILES = 500
MAX_OVERRIDE_TOTAL_BYTES = 512 * 1024 * 1024
MRPACK_ALLOWED_HOSTS = frozenset(
    {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
)
LOADER_KEYS = {
    "fabric-loader": "fabric",
    "neoforge": "neoforge",
    "forge": "forge",
    "quilt-loader": "quilt",
}


class ModpackError(ValueError):
    """The modpack cannot be imported; message is user-safe."""


class PackFile(BaseModel):
    path: str
    url: str
    checksum_algorithm: str | None
    checksum: str | None


class ModpackIndex(BaseModel):
    name: str
    minecraft_version: str
    loader: str
    loader_version: str | None
    files: list[PackFile]
    skipped_unsupported: list[str]


class ModpackResult(BaseModel):
    directory: str
    name: str
    minecraft_version: str
    distribution: str = "fabric"
    loader_version: str | None
    installed_files: int
    override_files: int
    skipped_unsupported: list[str]
    notes: list[str]


def _safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw.replace("\\", "/"))
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"..", ""} or part.startswith(".") for part in path.parts)
    ):
        raise ModpackError(f"The pack lists an unsafe file path: {raw[:120]}")
    return path


def _checked_url(raw: object) -> str:
    if not isinstance(raw, str):
        raise ModpackError("A pack file had no usable download link.")
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in MRPACK_ALLOWED_HOSTS:
        raise ModpackError(
            "A pack file wanted to download from a source outside the "
            "Modrinth pack specification's allowed hosts."
        )
    return raw


def parse_mrpack(data: bytes) -> ModpackIndex:
    """Read and validate modrinth.index.json from .mrpack bytes."""
    if len(data) > MAX_MRPACK_BYTES:
        raise ModpackError("The modpack file is larger than Blockstead accepts.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            raw = archive.read("modrinth.index.json")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ModpackError("That file is not a Modrinth modpack (.mrpack).") from exc
    try:
        index = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ModpackError("The modpack index could not be read.") from exc
    if not isinstance(index, dict) or index.get("game") not in {None, "minecraft"}:
        raise ModpackError("The modpack index had an unexpected shape.")
    dependencies = index.get("dependencies")
    if not isinstance(dependencies, dict) or not isinstance(dependencies.get("minecraft"), str):
        raise ModpackError("The modpack does not say which Minecraft version it needs.")
    loaders = [
        (LOADER_KEYS[key], value)
        for key, value in dependencies.items()
        if key in LOADER_KEYS and isinstance(value, str)
    ]
    if len(loaders) != 1:
        raise ModpackError("The modpack does not declare exactly one mod loader.")
    loader, loader_version = loaders[0]
    entries = index.get("files")
    if not isinstance(entries, list):
        raise ModpackError("The modpack index had an unexpected shape.")
    if len(entries) > MAX_PACK_FILES:
        raise ModpackError("The modpack lists more files than Blockstead accepts.")
    files: list[PackFile] = []
    skipped: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ModpackError("The modpack index had an unexpected shape.")
        path = str(_safe_relative(entry["path"]))
        env = entry.get("env")
        if isinstance(env, dict) and env.get("server") == "unsupported":
            skipped.append(path)
            continue
        downloads = entry.get("downloads")
        url = _checked_url(downloads[0] if isinstance(downloads, list) and downloads else None)
        hashes = entry.get("hashes") if isinstance(entry.get("hashes"), dict) else {}
        algorithm, checksum = None, None
        for candidate in ("sha512", "sha1"):
            value = hashes.get(candidate) if isinstance(hashes, dict) else None
            if isinstance(value, str):
                algorithm, checksum = candidate, value
                break
        if algorithm is None:
            raise ModpackError("A pack file has no checksum, so it cannot be verified.")
        files.append(PackFile(path=path, url=url, checksum_algorithm=algorithm, checksum=checksum))
    name = index.get("name")
    return ModpackIndex(
        name=name if isinstance(name, str) and name.strip() else "Modpack",
        minecraft_version=dependencies["minecraft"],
        loader=loader,
        loader_version=loader_version,
        files=files,
        skipped_unsupported=skipped,
    )


def _extract_overrides(data: bytes, target: Path) -> tuple[int, list[str]]:
    """Copy override members into the profile folder, safely, server last."""
    written = 0
    members = 0
    total = 0
    notes: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for prefix in ("overrides/", "server-overrides/"):
                for info in archive.infolist():
                    if not info.filename.startswith(prefix) or info.is_dir():
                        continue
                    members += 1
                    if members > MAX_OVERRIDE_FILES:
                        raise ModpackError(
                            "The pack contains more bundled override files than "
                            "Blockstead accepts."
                        )
                    relative = _safe_relative(info.filename[len(prefix) :])
                    if str(relative) == "eula.txt":
                        notes.append(
                            "The pack included eula.txt; Blockstead skipped it because "
                            "the EULA must be accepted explicitly."
                        )
                        continue
                    total += info.file_size
                    if total > MAX_OVERRIDE_TOTAL_BYTES:
                        raise ModpackError("The pack's bundled files are too large to import.")
                    destination = target / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open("wb") as sink:
                        shutil.copyfileobj(source, sink, length=1024 * 1024)
                    written += 1
    except ModpackError:
        raise
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ModpackError("The modpack's bundled override files could not be read.") from exc
    return written, notes


async def fetch_mrpack(client: httpx.AsyncClient, project_id: str, version_id: str | None) -> bytes:
    """Download the .mrpack file for a Modrinth modpack version, verified."""
    if version_id:
        version = await _version_by_id(client, version_id)
    else:
        version = await _best_version(
            client, project_id, ["fabric", "forge", "quilt", "neoforge"], None
        )
    files = version.get("files")
    usable = [item for item in files if isinstance(item, dict)] if isinstance(files, list) else []
    chosen = next(
        (
            item
            for item in sorted(usable, key=lambda item: not item.get("primary"))
            if isinstance(item.get("filename"), str) and str(item["filename"]).endswith(".mrpack")
        ),
        None,
    )
    if chosen is None:
        raise ModpackError("That Modrinth project has no downloadable .mrpack file.")
    url = _checked_url(chosen.get("url"))
    hashes = chosen.get("hashes")
    available_hashes = hashes if isinstance(hashes, dict) else {}
    algorithm: str | None = None
    published: str | None = None
    for candidate in ("sha512", "sha1"):
        value = available_hashes.get(candidate)
        if isinstance(value, str):
            algorithm, published = candidate, value
            break
    if algorithm is None or published is None:
        raise ModpackError("The Modrinth modpack has no published checksum.")
    digest = hashlib.new(algorithm)
    received = bytearray()
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if len(received) + len(chunk) > MAX_MRPACK_BYTES:
                    raise ModpackError("The modpack file is larger than Blockstead accepts.")
                received.extend(chunk)
                digest.update(chunk)
    except httpx.HTTPError as exc:
        raise ModpackError(f"The modpack download failed ({type(exc).__name__}).") from exc
    if digest.hexdigest() != published:
        raise ModpackError("The modpack did not match its published checksum and was discarded.")
    return bytes(received)


async def search_modpacks(client: httpx.AsyncClient, query: str) -> list[ModrinthProject]:
    payload = await _get_json(
        client,
        f"{MODRINTH_API}/search",
        {
            "query": query[:100],
            "facets": json.dumps(
                [
                    ["project_type:modpack"],
                    [
                        "categories:fabric",
                        "categories:forge",
                        "categories:quilt",
                        "categories:neoforge",
                    ],
                ]
            ),
            "limit": "20",
        },
    )
    hits = payload.get("hits") if isinstance(payload, dict) else None
    projects: list[ModrinthProject] = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict) or not isinstance(hit.get("project_id"), str):
            continue
        projects.append(
            ModrinthProject(
                project_id=hit["project_id"],
                slug=hit.get("slug") if isinstance(hit.get("slug"), str) else None,
                title=hit.get("title") if isinstance(hit.get("title"), str) else None,
                description=(
                    hit["description"][:300] if isinstance(hit.get("description"), str) else None
                ),
                downloads=(hit.get("downloads") if isinstance(hit.get("downloads"), int) else None),
                icon_url=hit.get("icon_url") if isinstance(hit.get("icon_url"), str) else None,
                author=hit.get("author") if isinstance(hit.get("author"), str) else None,
                project_type="modpack",
            )
        )
    return projects


async def install_modpack(
    client: httpx.AsyncClient,
    server_root: Path,
    directory_name: str,
    data: bytes,
    java_executable: str | None = None,
) -> ModpackResult:
    """Create a new profile folder from .mrpack bytes: files, overrides, launcher."""
    if not DIRECTORY_PATTERN.match(directory_name):
        raise ModpackError("Folder names use lowercase letters, digits, hyphens, and underscores.")
    index = parse_mrpack(data)
    if index.loader in {"forge", "quilt", "neoforge"} and java_executable is None:
        runtime = find_java(
            required_java_major(index.minecraft_version), discover_java_runtimes()
        )
        if runtime is None:
            raise ModpackError(
                "This modpack needs a compatible Java runtime to install its loader."
            )
        java_executable = runtime.path
    root = server_root.resolve(strict=True)
    target = root / directory_name
    if target.exists():
        raise ModpackError("A folder with that name already exists in the server root.")
    target.mkdir(mode=0o755)
    try:
        for pack_file in index.files:
            destination = target / PurePosixPath(pack_file.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            await download_verified_file(
                client,
                pack_file.url,
                destination.parent,
                destination.name,
                pack_file.checksum_algorithm,
                pack_file.checksum,
            )
        override_count, notes = _extract_overrides(data, target)
        launcher = await resolve_plan(
            client, index.loader, index.minecraft_version, index.loader_version
        )
        await install_loader(client, launcher, target, java_executable)
        notes.extend(launcher.notes)
    except (ModpackError, ProvisionError, ModrinthError, OSError):
        shutil.rmtree(target, ignore_errors=True)
        raise
    return ModpackResult(
        directory=str(target),
        name=index.name,
        minecraft_version=index.minecraft_version,
        distribution=index.loader,
        loader_version=index.loader_version,
        installed_files=len(index.files),
        override_files=override_count,
        skipped_unsupported=index.skipped_unsupported,
        notes=notes,
    )
