"""CurseForge catalog client: search and plan verified installs.

Only CurseForge's documented core API is used, and every request needs
the owner's own API key. Some authors disallow automated downloads;
those files expose no download link and are surfaced as browser-only
pages instead of being fetched. Downloads that are allowed are
checksum-verified with the published sha1.
"""

import re

import httpx

from .catalog import (
    CatalogError,
    CatalogProject,
    PlannedFile,
    ProjectVersion,
    SearchPage,
)
from .modrinth import JAR_NAME_PATTERN

CURSEFORGE_API = "https://api.curseforge.com/v1"
GAME_MINECRAFT = 432
CLASS_BUKKIT_PLUGINS = 5
CLASS_MC_MODS = 6
SEARCH_LIMIT = 20
MAX_SEARCH_OFFSET = 1000
MAX_LISTED_VERSIONS = 20
MAX_CATEGORY_FILTERS = 5
MAX_RESOLVED_FILES = 32
REQUIRED_DEPENDENCY = 3
SHA1_ALGO = 1

MODLOADER_TYPES = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
RELEASE_TYPES = {1: "release", 2: "beta", 3: "alpha"}
# Blockstead sort keys mapped to CurseForge sortField values.
SORT_FIELDS = {"relevance": 2, "downloads": 6, "follows": 2, "newest": 11, "updated": 3}
PROJECT_ID_PATTERN = re.compile(r"^[0-9]{1,12}$")
CATEGORY_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


class CurseForgeError(CatalogError):
    """The CurseForge request failed or returned unusable data; message is user-safe."""


def _class_for(distribution: str) -> int:
    if distribution == "paper":
        return CLASS_BUKKIT_PLUGINS
    if distribution in MODLOADER_TYPES:
        return CLASS_MC_MODS
    raise CurseForgeError(
        "This distribution does not have a CurseForge catalog. "
        "Only plugin or mod loader profiles can install from CurseForge."
    )


def _require_key(api_key: str | None) -> str:
    if not api_key:
        raise CurseForgeError(
            "CurseForge needs an API key before Blockstead can search it. "
            "Add your key in the CurseForge section of the catalog browser."
        )
    return api_key


async def _get_json(
    client: httpx.AsyncClient,
    api_key: str,
    url: str,
    params: list[tuple[str, str]],
) -> object:
    try:
        response = await client.get(
            url, params=tuple(params), headers={"x-api-key": api_key}
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CurseForgeError(
            f"CurseForge did not answer as expected ({type(exc).__name__})."
        ) from exc


def _data_list(payload: object) -> list[dict[str, object]]:
    data = payload.get("data") if isinstance(payload, dict) else None
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


async def _category_ids(
    client: httpx.AsyncClient, api_key: str, class_id: int, slugs: list[str]
) -> list[str]:
    if not slugs:
        return []
    payload = await _get_json(
        client,
        api_key,
        f"{CURSEFORGE_API}/categories",
        [("gameId", str(GAME_MINECRAFT)), ("classId", str(class_id))],
    )
    by_slug: dict[str, int] = {}
    for record in _data_list(payload):
        slug = record.get("slug")
        category_id = record.get("id")
        if isinstance(slug, str) and isinstance(category_id, int):
            by_slug[slug] = category_id
    return [str(by_slug[slug]) for slug in slugs if slug in by_slug]


async def search(
    client: httpx.AsyncClient,
    api_key: str | None,
    distribution: str,
    minecraft_version: str | None,
    query: str,
    categories: list[str] | None = None,
    sort: str = "relevance",
    offset: int = 0,
) -> SearchPage:
    key = _require_key(api_key)
    class_id = _class_for(distribution)
    if sort not in SORT_FIELDS:
        raise CurseForgeError("That sort order is not one CurseForge offers.")
    offset = max(0, min(offset, MAX_SEARCH_OFFSET))
    chosen = [item for item in (categories or []) if CATEGORY_SLUG_PATTERN.match(item)]
    if len(chosen) > MAX_CATEGORY_FILTERS:
        raise CurseForgeError("Pick at most five category filters.")
    params: list[tuple[str, str]] = [
        ("gameId", str(GAME_MINECRAFT)),
        ("classId", str(class_id)),
        ("searchFilter", query[:100]),
        ("sortField", str(SORT_FIELDS[sort])),
        ("sortOrder", "desc"),
        ("pageSize", str(SEARCH_LIMIT)),
        ("index", str(offset)),
    ]
    if minecraft_version:
        params.append(("gameVersion", minecraft_version))
    loader_type = MODLOADER_TYPES.get(distribution)
    if loader_type is not None:
        params.append(("modLoaderType", str(loader_type)))
    # CurseForge's search accepts one category filter; apply the first match.
    ids = await _category_ids(client, key, class_id, chosen[:1])
    params.extend(("categoryId", value) for value in ids[:1])
    payload = await _get_json(client, key, f"{CURSEFORGE_API}/mods/search", params)
    pagination = payload.get("pagination") if isinstance(payload, dict) else None
    total = pagination.get("totalCount") if isinstance(pagination, dict) else None
    projects: list[CatalogProject] = []
    for record in _data_list(payload):
        mod_id = record.get("id")
        if not isinstance(mod_id, int):
            continue
        links = record.get("links")
        website = links.get("websiteUrl") if isinstance(links, dict) else None
        logo = record.get("logo")
        authors = record.get("authors")
        first_author = (
            authors[0].get("name")
            if isinstance(authors, list) and authors and isinstance(authors[0], dict)
            else None
        )
        distribution_allowed = record.get("allowModDistribution")
        summary = record.get("summary")
        download_count = record.get("downloadCount")
        projects.append(
            CatalogProject(
                project_id=str(mod_id),
                slug=record.get("slug") if isinstance(record.get("slug"), str) else None,
                title=record.get("name") if isinstance(record.get("name"), str) else None,
                description=summary[:300] if isinstance(summary, str) else None,
                downloads=(
                    int(download_count)
                    if isinstance(download_count, int | float)
                    else None
                ),
                icon_url=(
                    logo.get("thumbnailUrl")
                    if isinstance(logo, dict) and isinstance(logo.get("thumbnailUrl"), str)
                    else None
                ),
                author=first_author if isinstance(first_author, str) else None,
                project_type="plugin" if class_id == CLASS_BUKKIT_PLUGINS else "mod",
                source="curseforge",
                page_url=website if isinstance(website, str) else None,
                installable=distribution_allowed is not False,
            )
        )
    return SearchPage(
        projects=projects,
        total=total if isinstance(total, int) else len(projects),
        offset=offset,
        limit=SEARCH_LIMIT,
    )


async def list_categories(
    client: httpx.AsyncClient, api_key: str | None, distribution: str
) -> list[str]:
    key = _require_key(api_key)
    class_id = _class_for(distribution)
    payload = await _get_json(
        client,
        key,
        f"{CURSEFORGE_API}/categories",
        [("gameId", str(GAME_MINECRAFT)), ("classId", str(class_id))],
    )
    slugs: list[str] = []
    for record in _data_list(payload):
        slug = record.get("slug")
        if isinstance(slug, str) and CATEGORY_SLUG_PATTERN.match(slug):
            slugs.append(slug)
    return sorted(set(slugs))


async def _mod_record(
    client: httpx.AsyncClient, api_key: str, project_id: str
) -> dict[str, object]:
    if not PROJECT_ID_PATTERN.match(project_id):
        raise CurseForgeError("That CurseForge project id is not one Blockstead accepts.")
    payload = await _get_json(client, api_key, f"{CURSEFORGE_API}/mods/{project_id}", [])
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CurseForgeError("A CurseForge project record had an unexpected shape.")
    return data


async def _file_records(
    client: httpx.AsyncClient,
    api_key: str,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
) -> list[dict[str, object]]:
    if not PROJECT_ID_PATTERN.match(project_id):
        raise CurseForgeError("That CurseForge project id is not one Blockstead accepts.")
    params: list[tuple[str, str]] = [("pageSize", str(MAX_LISTED_VERSIONS))]
    if minecraft_version:
        params.append(("gameVersion", minecraft_version))
    loader_type = MODLOADER_TYPES.get(distribution)
    if loader_type is not None:
        params.append(("modLoaderType", str(loader_type)))
    payload = await _get_json(
        client, api_key, f"{CURSEFORGE_API}/mods/{project_id}/files", params
    )
    return _data_list(payload)


def _website_file_url(website: object, file_id: object) -> str | None:
    if isinstance(website, str) and isinstance(file_id, int):
        return f"{website.rstrip('/')}/files/{file_id}"
    return None


async def list_project_versions(
    client: httpx.AsyncClient,
    api_key: str | None,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
) -> list[ProjectVersion]:
    """Files of one CurseForge project that suit this server, newest first."""
    key = _require_key(api_key)
    _class_for(distribution)
    mod = await _mod_record(client, key, project_id)
    links = mod.get("links")
    website = links.get("websiteUrl") if isinstance(links, dict) else None
    versions: list[ProjectVersion] = []
    for record in await _file_records(client, key, distribution, minecraft_version, project_id):
        file_id = record.get("id")
        if not isinstance(file_id, int):
            continue
        display = record.get("displayName")
        date = record.get("fileDate")
        game_versions = record.get("gameVersions")
        release_type = record.get("releaseType")
        download_url = record.get("downloadUrl")
        versions.append(
            ProjectVersion(
                version_id=str(file_id),
                version_number=display[:100] if isinstance(display, str) else None,
                version_type=(
                    RELEASE_TYPES.get(release_type) if isinstance(release_type, int) else None
                ),
                date_published=date[:32] if isinstance(date, str) else None,
                game_versions=(
                    [item for item in game_versions if isinstance(item, str)][:20]
                    if isinstance(game_versions, list)
                    else []
                ),
                loaders=[distribution],
                external_url=(
                    None
                    if isinstance(download_url, str)
                    else _website_file_url(website, file_id)
                ),
            )
        )
        if len(versions) >= MAX_LISTED_VERSIONS:
            break
    return versions


def _planned_from(
    record: dict[str, object], project_id: str, required_by: str | None
) -> PlannedFile:
    download_url = record.get("downloadUrl")
    if not isinstance(download_url, str):
        raise CurseForgeError(
            "The author only allows this file to be downloaded from the CurseForge "
            "website. Open the project page in your browser and use Upload a jar instead."
        )
    if not download_url.startswith("https://"):
        raise CurseForgeError("A CurseForge file had a download link Blockstead does not accept.")
    file_name = record.get("fileName")
    if not isinstance(file_name, str) or not JAR_NAME_PATTERN.match(file_name):
        raise CurseForgeError("A CurseForge file had a name Blockstead does not accept.")
    sha1 = None
    hashes = record.get("hashes")
    for item in hashes if isinstance(hashes, list) else []:
        if isinstance(item, dict) and item.get("algo") == SHA1_ALGO:
            value = item.get("value")
            if isinstance(value, str):
                sha1 = value
                break
    file_id = record.get("id")
    display = record.get("displayName")
    return PlannedFile(
        project_id=project_id,
        version_id=str(file_id) if isinstance(file_id, int) else "unknown",
        version_number=display[:100] if isinstance(display, str) else None,
        file_name=file_name,
        url=download_url,
        checksum_algorithm="sha1" if sha1 else None,
        checksum=sha1,
        required_by=required_by,
    )


def _best_record(records: list[dict[str, object]]) -> dict[str, object] | None:
    release = next((item for item in records if item.get("releaseType") == 1), None)
    return release or (records[0] if records else None)


async def plan_install(
    client: httpx.AsyncClient,
    api_key: str | None,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
    version_id: str | None = None,
) -> list[PlannedFile]:
    """Resolve the chosen file plus its required-dependency closure."""
    key = _require_key(api_key)
    _class_for(distribution)
    records = await _file_records(client, key, distribution, minecraft_version, project_id)
    if version_id:
        root = next(
            (item for item in records if str(item.get("id")) == version_id), None
        )
        if root is None:
            raise CurseForgeError("That CurseForge file does not suit this server.")
    else:
        root = _best_record(records)
        if root is None:
            raise CurseForgeError(
                "CurseForge has no compatible file of that project for this server."
            )
    planned = [_planned_from(root, project_id, None)]
    seen_projects = {project_id}
    queue: list[tuple[dict[str, object], str]] = [(root, planned[0].file_name)]
    while queue:
        record, parent_name = queue.pop(0)
        dependencies = record.get("dependencies")
        for dependency in dependencies if isinstance(dependencies, list) else []:
            if not isinstance(dependency, dict):
                continue
            if dependency.get("relationType") != REQUIRED_DEPENDENCY:
                continue
            dep_id = dependency.get("modId")
            if not isinstance(dep_id, int) or str(dep_id) in seen_projects:
                continue
            seen_projects.add(str(dep_id))
            dep_records = await _file_records(
                client, key, distribution, minecraft_version, str(dep_id)
            )
            dep_record = _best_record(dep_records)
            if dep_record is None:
                raise CurseForgeError(
                    "A required dependency has no compatible CurseForge file for this server."
                )
            if len(planned) >= MAX_RESOLVED_FILES:
                raise CurseForgeError(
                    "That project needs more dependencies than Blockstead will "
                    "install automatically."
                )
            entry = _planned_from(dep_record, str(dep_id), parent_name)
            planned.append(entry)
            queue.append((dep_record, entry.file_name))
    return planned
