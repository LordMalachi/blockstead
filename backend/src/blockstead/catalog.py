"""Shared data shapes for extension catalogs.

Every catalog client (Modrinth, Hangar) maps its own API records into
these models so the dashboard can search, list versions, and plan
installs the same way regardless of where a project is hosted.
"""

from pydantic import BaseModel, Field


class CatalogError(ValueError):
    """The catalog request failed or returned unusable data; message is user-safe."""


class CatalogProject(BaseModel):
    project_id: str
    slug: str | None
    title: str | None
    description: str | None
    downloads: int | None
    icon_url: str | None = None
    author: str | None = None
    project_type: str | None = None
    source: str = "modrinth"
    page_url: str | None = None
    #: False when the host allows browsing but not automated downloads.
    installable: bool = True


class SearchPage(BaseModel):
    projects: list[CatalogProject]
    total: int
    offset: int
    limit: int


class ProjectVersion(BaseModel):
    version_id: str
    version_number: str | None
    version_type: str | None
    date_published: str | None
    game_versions: list[str]
    loaders: list[str]
    external_url: str | None = None
    required_plugins: list[str] = Field(default_factory=list)


class PlannedFile(BaseModel):
    project_id: str
    version_id: str
    version_number: str | None
    file_name: str
    url: str
    checksum_algorithm: str | None
    checksum: str | None
    required_by: str | None
    #: Paper plugin dependencies are named, rather than catalog-addressable IDs.
    #: The API checks that they are already present before installing the jar.
    required_plugins: list[str] = []
