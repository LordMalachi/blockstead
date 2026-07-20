"""Modrinth catalog client: search projects and plan verified installs.

Only Modrinth's documented public API is used. Planning resolves the
required-dependency closure up front so the owner sees every file that
would be installed before anything is downloaded.
"""

import json
import re

import httpx

from .catalog import (
    CatalogError,
    CatalogProject,
    PlannedFile,
    ProjectVersion,
    SearchPage,
)

MODRINTH_API = "https://api.modrinth.com/v2"
SEARCH_LIMIT = 20
MAX_RESOLVED_FILES = 32
MAX_SEARCH_OFFSET = 1000
MAX_LISTED_VERSIONS = 20
MAX_CATEGORY_FILTERS = 5
SORT_INDEXES = frozenset({"relevance", "downloads", "follows", "newest", "updated"})

JAR_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\- ]{0,127}\.jar$")
CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

LOADER_FILTERS: dict[str, list[str]] = {
    "paper": ["paper", "spigot", "bukkit"],
    "fabric": ["fabric"],
    "forge": ["forge"],
    "quilt": ["quilt"],
    "neoforge": ["neoforge"],
}
PROJECT_TYPES: dict[str, str] = {
    "paper": "plugin",
    "fabric": "mod",
    "forge": "mod",
    "quilt": "mod",
    "neoforge": "mod",
}


class ModrinthError(CatalogError):
    """The Modrinth request failed or returned unusable data; message is user-safe."""


# Backward-compatible alias: Modrinth records are plain catalog projects.
ModrinthProject = CatalogProject


def _loaders_for(distribution: str) -> list[str]:
    loaders = LOADER_FILTERS.get(distribution)
    if loaders is None:
        raise ModrinthError(
            "This distribution does not have a Modrinth catalog. "
            "Only plugin or mod loader profiles can install from Modrinth."
        )
    return loaders


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, str]) -> object:
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ModrinthError(f"Modrinth did not answer as expected ({type(exc).__name__}).") from exc


async def search(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    query: str,
    categories: list[str] | None = None,
    sort: str = "relevance",
    offset: int = 0,
) -> SearchPage:
    loaders = _loaders_for(distribution)
    if sort not in SORT_INDEXES:
        raise ModrinthError("That sort order is not one Modrinth offers.")
    offset = max(0, min(offset, MAX_SEARCH_OFFSET))
    chosen = [item for item in (categories or []) if CATEGORY_PATTERN.match(item)]
    if len(chosen) > MAX_CATEGORY_FILTERS:
        raise ModrinthError("Pick at most five category filters.")
    facets: list[list[str]] = [
        [f"project_type:{PROJECT_TYPES[distribution]}"],
        [f"categories:{loader}" for loader in loaders],
        ["server_side:required", "server_side:optional"],
    ]
    # Each chosen category is its own facet group, so filters narrow (AND).
    facets.extend([f"categories:{category}"] for category in chosen)
    if minecraft_version:
        facets.append([f"versions:{minecraft_version}"])
    payload = await _get_json(
        client,
        f"{MODRINTH_API}/search",
        {
            "query": query[:100],
            "facets": json.dumps(facets),
            "limit": str(SEARCH_LIMIT),
            "offset": str(offset),
            "index": sort,
        },
    )
    hits = payload.get("hits") if isinstance(payload, dict) else None
    total = payload.get("total_hits") if isinstance(payload, dict) else None
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
                project_type=(
                    hit.get("project_type") if isinstance(hit.get("project_type"), str) else None
                ),
                source="modrinth",
                page_url=(
                    f"https://modrinth.com/{PROJECT_TYPES[distribution]}/{hit['slug']}"
                    if isinstance(hit.get("slug"), str)
                    else None
                ),
            )
        )
    return SearchPage(
        projects=projects,
        total=total if isinstance(total, int) else len(projects),
        offset=offset,
        limit=SEARCH_LIMIT,
    )


async def list_categories(client: httpx.AsyncClient, distribution: str) -> list[str]:
    """Category names Modrinth offers for this distribution's project type."""
    _loaders_for(distribution)
    payload = await _get_json(client, f"{MODRINTH_API}/tag/category", {})
    # Modrinth's tag list has no separate "plugin" type; plugins share mod categories.
    project_type = PROJECT_TYPES[distribution]
    if project_type == "plugin":
        project_type = "mod"
    names = [
        entry["name"]
        for entry in (payload if isinstance(payload, list) else [])
        if isinstance(entry, dict)
        and entry.get("project_type") == project_type
        and entry.get("header") == "categories"
        and isinstance(entry.get("name"), str)
        and CATEGORY_PATTERN.match(entry["name"])
    ]
    return sorted(set(names))


async def list_project_versions(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
) -> list[ProjectVersion]:
    """Versions of one project that suit this server, newest first."""
    loaders = _loaders_for(distribution)
    params: dict[str, str] = {"loaders": json.dumps(loaders), "include_changelog": "false"}
    if minecraft_version:
        params["game_versions"] = json.dumps([minecraft_version])
    payload = await _get_json(client, f"{MODRINTH_API}/project/{project_id}/version", params)
    versions: list[ProjectVersion] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        number = item.get("version_number")
        kind = item.get("version_type")
        published = item.get("date_published")
        game_versions = item.get("game_versions")
        item_loaders = item.get("loaders")
        versions.append(
            ProjectVersion(
                version_id=item["id"],
                version_number=number[:100] if isinstance(number, str) else None,
                version_type=kind if isinstance(kind, str) else None,
                date_published=published[:32] if isinstance(published, str) else None,
                game_versions=[
                    value for value in game_versions if isinstance(value, str)
                ][:20]
                if isinstance(game_versions, list)
                else [],
                loaders=[value for value in item_loaders if isinstance(value, str)][:10]
                if isinstance(item_loaders, list)
                else [],
            )
        )
        if len(versions) >= MAX_LISTED_VERSIONS:
            break
    return versions


def _pick_file(version: dict[str, object]) -> dict[str, object]:
    files = version.get("files")
    usable = [item for item in files if isinstance(item, dict)] if isinstance(files, list) else []
    if not usable:
        raise ModrinthError("A Modrinth version listed no downloadable files.")
    primary = next((item for item in usable if item.get("primary")), usable[0])
    return primary


def _planned_from(version: dict[str, object], required_by: str | None) -> PlannedFile:
    file = _pick_file(version)
    file_name = file.get("filename")
    url = file.get("url")
    if not isinstance(file_name, str) or not JAR_NAME_PATTERN.match(file_name):
        raise ModrinthError("A Modrinth file had a name Blockstead does not accept.")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ModrinthError("A Modrinth file had a download link Blockstead does not accept.")
    raw_hashes = file.get("hashes")
    hashes: dict[str, object] = raw_hashes if isinstance(raw_hashes, dict) else {}
    algorithm, checksum = None, None
    for candidate in ("sha512", "sha1"):
        value = hashes.get(candidate)
        if isinstance(value, str):
            algorithm, checksum = candidate, value
            break
    project_id = version.get("project_id")
    version_id = version.get("id")
    if not isinstance(project_id, str) or not isinstance(version_id, str):
        raise ModrinthError("A Modrinth version record had an unexpected shape.")
    number = version.get("version_number")
    return PlannedFile(
        project_id=project_id,
        version_id=version_id,
        version_number=number if isinstance(number, str) else None,
        file_name=file_name,
        url=url,
        checksum_algorithm=algorithm,
        checksum=checksum,
        required_by=required_by,
    )


MAX_UPDATE_HASHES = 200


async def check_updates(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    sha512_hashes: list[str],
) -> dict[str, PlannedFile | None]:
    """Map installed-file sha512 hashes to the newest compatible Modrinth file.

    A hash appears in the result only when Modrinth recognizes it: mapped to
    None when the installed file already is the newest compatible one, or to
    the newer planned file otherwise. Unrecognized hashes are absent.
    """
    loaders = _loaders_for(distribution)
    hashes = [item for item in sha512_hashes if isinstance(item, str)][:MAX_UPDATE_HASHES]
    if not hashes:
        return {}
    body: dict[str, object] = {
        "hashes": hashes,
        "algorithm": "sha512",
        "loaders": loaders,
    }
    if minecraft_version:
        body["game_versions"] = [minecraft_version]
    try:
        response = await client.post(f"{MODRINTH_API}/version_files/update", json=body)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ModrinthError(f"Modrinth did not answer as expected ({type(exc).__name__}).") from exc
    updates: dict[str, PlannedFile | None] = {}
    for installed_hash, version in payload.items() if isinstance(payload, dict) else []:
        if installed_hash not in hashes or not isinstance(version, dict):
            continue
        try:
            planned = _planned_from(version, None)
        except ModrinthError:
            continue
        already_newest = (
            planned.checksum_algorithm == "sha512" and planned.checksum == installed_hash
        )
        updates[installed_hash] = None if already_newest else planned
    return updates


async def _version_by_id(client: httpx.AsyncClient, version_id: str) -> dict[str, object]:
    payload = await _get_json(client, f"{MODRINTH_API}/version/{version_id}", {})
    if not isinstance(payload, dict):
        raise ModrinthError("A Modrinth version record had an unexpected shape.")
    return payload


async def _best_version(
    client: httpx.AsyncClient,
    project_id: str,
    loaders: list[str],
    minecraft_version: str | None,
) -> dict[str, object]:
    params: dict[str, str] = {
        "loaders": json.dumps(loaders),
        "include_changelog": "false",
    }
    if minecraft_version:
        params["game_versions"] = json.dumps([minecraft_version])
    payload = await _get_json(client, f"{MODRINTH_API}/project/{project_id}/version", params)
    versions = (
        [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []
    )
    if not versions:
        raise ModrinthError("Modrinth has no compatible version of that project for this server.")
    releases = [item for item in versions if item.get("version_type") == "release"]
    return releases[0] if releases else versions[0]


async def plan_install(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
    version_id: str | None = None,
) -> list[PlannedFile]:
    """Resolve the chosen version plus its required-dependency closure."""
    loaders = _loaders_for(distribution)
    if version_id:
        root = await _version_by_id(client, version_id)
        root_loaders = root.get("loaders")
        if isinstance(root_loaders, list) and not (set(root_loaders) & set(loaders)):
            raise ModrinthError("That Modrinth version does not support this server's loader.")
        game_versions = root.get("game_versions")
        if (
            minecraft_version
            and isinstance(game_versions, list)
            and minecraft_version not in game_versions
        ):
            raise ModrinthError("That Modrinth version does not support this Minecraft version.")
    else:
        root = await _best_version(client, project_id, loaders, minecraft_version)
    planned: list[PlannedFile] = [_planned_from(root, None)]
    seen_projects = {planned[0].project_id}
    queue: list[tuple[dict[str, object], str]] = [(root, planned[0].file_name)]
    while queue:
        version, parent_name = queue.pop(0)
        dependencies = version.get("dependencies")
        for dependency in dependencies if isinstance(dependencies, list) else []:
            if not isinstance(dependency, dict):
                continue
            if dependency.get("dependency_type") != "required":
                continue
            dep_version_id = dependency.get("version_id")
            dep_project_id = dependency.get("project_id")
            if isinstance(dep_version_id, str):
                dep_version = await _version_by_id(client, dep_version_id)
            elif isinstance(dep_project_id, str):
                if dep_project_id in seen_projects:
                    continue
                dep_version = await _best_version(
                    client, dep_project_id, loaders, minecraft_version
                )
            else:
                continue
            entry = _planned_from(dep_version, parent_name)
            if entry.project_id in seen_projects:
                continue
            seen_projects.add(entry.project_id)
            if len(planned) >= MAX_RESOLVED_FILES:
                raise ModrinthError(
                    "That project needs more dependencies than Blockstead will "
                    "install automatically."
                )
            planned.append(entry)
            queue.append((dep_version, entry.file_name))
    return planned
