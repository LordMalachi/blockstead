"""Read squaremap's generated web-server configuration without changing it."""

from pathlib import Path

import yaml
from pydantic import BaseModel

MAX_CONFIG_BYTES = 1_000_000
DEFAULT_BIND = "0.0.0.0"  # noqa: S104 - upstream's documented display default, not a listener
DEFAULT_PORT = 8080


class SharedMapView(BaseModel):
    config_present: bool
    config_path: str | None
    internal_webserver_enabled: bool
    bind: str
    port: int
    problem: str | None = None


def _candidate_paths(distribution: str) -> tuple[Path, ...]:
    if distribution == "paper":
        return (Path("plugins/squaremap/config.yml"),)
    if distribution in {"fabric", "quilt", "forge", "neoforge"}:
        return (Path("config/squaremap/config.yml"),)
    return ()


def _defaults(problem: str | None = None) -> SharedMapView:
    return SharedMapView(
        config_present=False,
        config_path=None,
        internal_webserver_enabled=True,
        bind=DEFAULT_BIND,
        port=DEFAULT_PORT,
        problem=problem,
    )


def read_shared_map(server_directory: Path, distribution: str) -> SharedMapView:
    """Return the effective built-in web-server address from a bounded YAML file."""
    root = server_directory.resolve(strict=True)
    relative = next(
        (candidate for candidate in _candidate_paths(distribution) if (root / candidate).is_file()),
        None,
    )
    if relative is None:
        return _defaults()

    path = root / relative
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if resolved.stat().st_size > MAX_CONFIG_BYTES:
            return _defaults("squaremap's config.yml is too large for Blockstead to read safely.")
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, yaml.YAMLError):
        return _defaults("squaremap's config.yml could not be read safely.")

    if not isinstance(payload, dict):
        return _defaults("squaremap's config.yml does not contain the expected settings.")
    settings = payload.get("settings")
    webserver = settings.get("internal-webserver") if isinstance(settings, dict) else None
    if not isinstance(webserver, dict):
        return _defaults("squaremap's config.yml does not contain its web server settings.")

    bind = webserver.get("bind", DEFAULT_BIND)
    port = webserver.get("port", DEFAULT_PORT)
    enabled = webserver.get("enabled", True)
    if not isinstance(bind, str) or not bind.strip():
        bind = DEFAULT_BIND
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        port = DEFAULT_PORT
    if not isinstance(enabled, bool):
        enabled = True
    return SharedMapView(
        config_present=True,
        config_path=relative.as_posix(),
        internal_webserver_enabled=enabled,
        bind=bind.strip(),
        port=port,
    )
