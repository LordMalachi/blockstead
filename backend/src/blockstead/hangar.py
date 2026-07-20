"""Hangar (PaperMC) catalog client: search and plan verified plugin installs.

Only Hangar's documented public API is used. Hangar hosts Paper-family
plugins, so mod-loader distributions are refused. Files hosted outside
Hangar carry no published checksum and are never downloaded
automatically; they are surfaced as browser-only links instead.
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

HANGAR_API = "https://hangar.papermc.io/api/v1"
HANGAR_SITE = "https://hangar.papermc.io"
SEARCH_LIMIT = 20  # Hangar rejects limits above 25.
MAX_SEARCH_OFFSET = 1000
MAX_LISTED_VERSIONS = 20
MAX_CATEGORY_FILTERS = 5

# Hangar's category list is a fixed enum in its API specification.
CATEGORIES = [
    "admin_tools",
    "chat",
    "dev_tools",
    "economy",
    "gameplay",
    "games",
    "misc",
    "protection",
    "role_playing",
    "world_management",
]
# Blockstead sort keys mapped to Hangar's sort values; None means
# Hangar's own relevance ordering for the query.
SORTS: dict[str, str | None] = {
    "relevance": None,
    "downloads": "downloads",
    "follows": "stars",
    "newest": "newest",
    "updated": "updated",
}
PROJECT_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,64}$")
VERSION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class HangarError(CatalogError):
    """The Hangar request failed or returned unusable data; message is user-safe."""


def _require_paper(distribution: str) -> None:
    if distribution != "paper":
        raise HangarError(
            "Hangar only lists Paper-family plugins. Mod loader profiles use Modrinth."
        )


async def _get_json(
    client: httpx.AsyncClient, url: str, params: list[tuple[str, str]]
) -> object:
    try:
        response = await client.get(url, params=tuple(params))
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HangarError(f"Hangar did not answer as expected ({type(exc).__name__}).") from exc


async def search(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    query: str,
    categories: list[str] | None = None,
    sort: str = "relevance",
    offset: int = 0,
) -> SearchPage:
    _require_paper(distribution)
    if sort not in SORTS:
        raise HangarError("That sort order is not one Hangar offers.")
    offset = max(0, min(offset, MAX_SEARCH_OFFSET))
    chosen = [item for item in (categories or []) if item in CATEGORIES]
    if len(chosen) > MAX_CATEGORY_FILTERS:
        raise HangarError("Pick at most five category filters.")
    params: list[tuple[str, str]] = [
        ("query", query[:100]),
        ("platform", "PAPER"),
        ("limit", str(SEARCH_LIMIT)),
        ("offset", str(offset)),
    ]
    if minecraft_version:
        params.append(("version", minecraft_version))
    mapped = SORTS[sort]
    if mapped:
        params.append(("sort", mapped))
    params.extend(("category", category) for category in chosen)
    payload = await _get_json(client, f"{HANGAR_API}/projects", params)
    records = payload.get("result") if isinstance(payload, dict) else None
    pagination = payload.get("pagination") if isinstance(payload, dict) else None
    total = pagination.get("count") if isinstance(pagination, dict) else None
    projects: list[CatalogProject] = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        namespace = record.get("namespace")
        owner = namespace.get("owner") if isinstance(namespace, dict) else None
        slug = namespace.get("slug") if isinstance(namespace, dict) else None
        if (
            not isinstance(owner, str)
            or not isinstance(slug, str)
            or not PROJECT_PATH_PATTERN.match(f"{owner}/{slug}")
        ):
            continue
        stats = record.get("stats")
        downloads = stats.get("downloads") if isinstance(stats, dict) else None
        projects.append(
            CatalogProject(
                project_id=f"{owner}/{slug}",
                slug=slug,
                title=record.get("name") if isinstance(record.get("name"), str) else slug,
                description=(
                    record["description"][:300]
                    if isinstance(record.get("description"), str)
                    else None
                ),
                downloads=downloads if isinstance(downloads, int) else None,
                icon_url=(
                    record.get("avatarUrl") if isinstance(record.get("avatarUrl"), str) else None
                ),
                author=owner,
                project_type="plugin",
                source="hangar",
                page_url=f"{HANGAR_SITE}/{owner}/{slug}",
            )
        )
    return SearchPage(
        projects=projects,
        total=total if isinstance(total, int) else len(projects),
        offset=offset,
        limit=SEARCH_LIMIT,
    )


async def list_categories(client: httpx.AsyncClient, distribution: str) -> list[str]:
    """Hangar's fixed plugin categories; the client and network are unused."""
    _require_paper(distribution)
    return list(CATEGORIES)


async def _fetch_version_records(
    client: httpx.AsyncClient,
    minecraft_version: str | None,
    project_id: str,
) -> list[dict[str, object]]:
    if not PROJECT_PATH_PATTERN.match(project_id):
        raise HangarError("That Hangar project id is not one Blockstead accepts.")
    params: list[tuple[str, str]] = [
        ("platform", "PAPER"),
        ("limit", str(MAX_LISTED_VERSIONS)),
        ("offset", "0"),
    ]
    if minecraft_version:
        params.append(("platformVersion", minecraft_version))
    payload = await _get_json(client, f"{HANGAR_API}/projects/{project_id}/versions", params)
    records = payload.get("result") if isinstance(payload, dict) else None
    return [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []


def _paper_download(record: dict[str, object]) -> dict[str, object]:
    downloads = record.get("downloads")
    paper = downloads.get("PAPER") if isinstance(downloads, dict) else None
    return paper if isinstance(paper, dict) else {}


def _channel_name(record: dict[str, object]) -> str | None:
    channel = record.get("channel")
    name = channel.get("name") if isinstance(channel, dict) else None
    return name.lower() if isinstance(name, str) else None


async def list_project_versions(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
) -> list[ProjectVersion]:
    """Versions of one Hangar plugin that suit this server, newest first."""
    _require_paper(distribution)
    versions: list[ProjectVersion] = []
    for record in await _fetch_version_records(client, minecraft_version, project_id):
        name = record.get("name")
        if not isinstance(name, str) or not VERSION_NAME_PATTERN.match(name):
            continue
        paper = _paper_download(record)
        external = paper.get("externalUrl")
        created = record.get("createdAt")
        platform_deps = record.get("platformDependencies")
        raw_games = platform_deps.get("PAPER") if isinstance(platform_deps, dict) else None
        plugin_deps = record.get("pluginDependencies")
        raw_plugins = plugin_deps.get("PAPER") if isinstance(plugin_deps, dict) else None
        versions.append(
            ProjectVersion(
                version_id=name,
                version_number=name,
                version_type=_channel_name(record),
                date_published=created[:32] if isinstance(created, str) else None,
                game_versions=(
                    [item for item in raw_games if isinstance(item, str)][:20]
                    if isinstance(raw_games, list)
                    else []
                ),
                loaders=["paper"],
                external_url=external if isinstance(external, str) else None,
                required_plugins=sorted(
                    str(dep["name"])[:100]
                    for dep in (raw_plugins if isinstance(raw_plugins, list) else [])
                    if isinstance(dep, dict) and dep.get("required") and dep.get("name")
                ),
            )
        )
    return versions


async def plan_install(
    client: httpx.AsyncClient,
    distribution: str,
    minecraft_version: str | None,
    project_id: str,
    version_id: str | None = None,
) -> list[PlannedFile]:
    """Resolve one Hangar version to a single checksum-verified download."""
    _require_paper(distribution)
    records = await _fetch_version_records(client, minecraft_version, project_id)
    record: dict[str, object] | None = None
    if version_id:
        record = next((item for item in records if item.get("name") == version_id), None)
        if record is None:
            raise HangarError("That Hangar version does not suit this server.")
    else:
        record = next(
            (item for item in records if _channel_name(item) == "release"),
            records[0] if records else None,
        )
        if record is None:
            raise HangarError("Hangar has no compatible version of that plugin for this server.")
    paper = _paper_download(record)
    url = paper.get("downloadUrl")
    if not isinstance(url, str):
        raise HangarError(
            "That file is hosted outside Hangar, so Blockstead cannot verify it. "
            "Open the plugin's page in your browser and use Upload a jar instead."
        )
    if not url.startswith("https://"):
        raise HangarError("A Hangar file had a download link Blockstead does not accept.")
    file_info = paper.get("fileInfo")
    file_name = file_info.get("name") if isinstance(file_info, dict) else None
    if not isinstance(file_name, str) or not JAR_NAME_PATTERN.match(file_name):
        raise HangarError("A Hangar file had a name Blockstead does not accept.")
    sha256 = file_info.get("sha256Hash") if isinstance(file_info, dict) else None
    name = record.get("name")
    return [
        PlannedFile(
            project_id=project_id,
            version_id=name if isinstance(name, str) else "unknown",
            version_number=name if isinstance(name, str) else None,
            file_name=file_name,
            url=url,
            checksum_algorithm="sha256" if isinstance(sha256, str) else None,
            checksum=sha256 if isinstance(sha256, str) else None,
            required_by=None,
        )
    ]
