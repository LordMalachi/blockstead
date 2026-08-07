"""Read and safely tune squaremap's generated web-server configuration."""

import hashlib
import re
import shutil
from datetime import UTC, datetime
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
    normal_render_threads: int | None = None
    background_render_threads: int | None = None
    problem: str | None = None


class SharedMapLowResourceResult(BaseModel):
    config_path: str
    backup_path: str
    normal_render_threads: int
    background_render_threads: int


class SharedMapError(ValueError):
    """A squaremap configuration action was unsafe or unavailable."""


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
    world_settings = payload.get("world-settings")
    default = world_settings.get("default") if isinstance(world_settings, dict) else None
    map_settings = default.get("map") if isinstance(default, dict) else None
    normal_threads = (
        map_settings.get("max-render-threads") if isinstance(map_settings, dict) else None
    )
    background = map_settings.get("background-render") if isinstance(map_settings, dict) else None
    background_threads = (
        background.get("max-render-threads") if isinstance(background, dict) else None
    )
    if isinstance(normal_threads, bool) or not isinstance(normal_threads, int):
        normal_threads = None
    if isinstance(background_threads, bool) or not isinstance(background_threads, int):
        background_threads = None
    return SharedMapView(
        config_present=True,
        config_path=relative.as_posix(),
        internal_webserver_enabled=enabled,
        bind=bind.strip(),
        port=port,
        normal_render_threads=normal_threads,
        background_render_threads=background_threads,
    )


def local_health_url(view: SharedMapView) -> tuple[str | None, str | None]:
    """Return a safe loopback-only target for a map health probe.

    A map config is owner-controlled but must not become a dashboard SSRF
    target. Wildcard and loopback listeners are safe to probe locally; a
    specific LAN address is reported as configured-but-not-safely-probeable.
    """

    if not view.config_present:
        return None, "Waiting for squaremap to generate config.yml."
    if not view.internal_webserver_enabled:
        return None, "squaremap's built-in web server is disabled."
    if view.bind in {"0.0.0.0", "::", "127.0.0.1", "localhost", "::1"}:  # noqa: S104
        return f"http://127.0.0.1:{view.port}/", None
    return None, "Blockstead only probes wildcard or loopback map listeners locally."


def _find_child_key(
    lines: list[str], start: int, parent_indent: int, key: str
) -> tuple[int, int] | None:
    expression = re.compile(rf"^(?P<indent>\s*){re.escape(key)}\s*:")
    child_indent: int | None = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            return None
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        match = expression.match(line)
        if match is not None:
            return index, len(match.group("indent"))
    return None


def _replace_scalar(lines: list[str], index: int, key: str, value: int) -> None:
    expression = re.compile(
        rf"^(?P<prefix>\s*{re.escape(key)}\s*:\s*)[^#\r\n]*(?P<comment>\s+#.*)?$"
    )
    match = expression.match(lines[index])
    if match is None:
        raise SharedMapError("squaremap's render-thread setting has an unsupported format.")
    lines[index] = f"{match.group('prefix')}{value}{match.group('comment') or ''}\n"


def apply_low_resource_profile(
    server_directory: Path, distribution: str
) -> SharedMapLowResourceResult:
    """Set squaremap's two render pools to one thread with a private backup."""

    root = server_directory.resolve(strict=True)
    relative = next(
        (candidate for candidate in _candidate_paths(distribution) if (root / candidate).is_file()),
        None,
    )
    if relative is None:
        raise SharedMapError("Start squaremap once so it can generate config.yml first.")
    target = root / relative
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
        original = resolved.read_bytes()
    except (OSError, ValueError) as exc:
        raise SharedMapError("squaremap's config.yml could not be read safely.") from exc
    if len(original) > MAX_CONFIG_BYTES:
        raise SharedMapError("squaremap's config.yml is too large for Blockstead to edit safely.")
    try:
        decoded = original.decode("utf-8")
        payload = yaml.safe_load(decoded)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SharedMapError("squaremap's config.yml is not valid UTF-8 YAML.") from exc
    if not isinstance(payload, dict):
        raise SharedMapError("squaremap's config.yml has an unsupported structure.")

    lines = decoded.splitlines(keepends=True)
    world = next(
        (
            (index, len(line) - len(line.lstrip(" ")))
            for index, line in enumerate(lines)
            if re.match(r"^\s*world-settings\s*:\s*(?:#.*)?$", line)
        ),
        None,
    )
    if world is None:
        raise SharedMapError("squaremap's config.yml has no world-settings.default.map section.")
    default = _find_child_key(lines, world[0], world[1], "default")
    map_settings = (
        _find_child_key(lines, default[0], default[1], "map") if default is not None else None
    )
    background = (
        _find_child_key(lines, map_settings[0], map_settings[1], "background-render")
        if map_settings is not None
        else None
    )
    normal = (
        _find_child_key(lines, map_settings[0], map_settings[1], "max-render-threads")
        if map_settings is not None
        else None
    )
    background_threads = (
        _find_child_key(lines, background[0], background[1], "max-render-threads")
        if background is not None
        else None
    )
    if normal is None or background_threads is None:
        raise SharedMapError(
            "squaremap's generated config.yml is missing one of its render-thread settings."
        )
    _replace_scalar(lines, normal[0], "max-render-threads", 1)
    _replace_scalar(lines, background_threads[0], "max-render-threads", 1)
    updated = "".join(lines).encode("utf-8")
    try:
        yaml.safe_load(updated.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:  # pragma: no cover - defensive
        raise SharedMapError("Blockstead could not produce valid squaremap YAML.") from exc

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(original).hexdigest()[:12]
    backup = root / ".blockstead-config-backups" / f"squaremap-config.{stamp}.{digest}.bak"
    staging = resolved.with_name(f".{resolved.name}.blockstead.tmp")
    try:
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(resolved, backup)
        staging.write_bytes(updated)
        staging.chmod(resolved.stat().st_mode)
        staging.replace(resolved)
    except OSError as exc:
        staging.unlink(missing_ok=True)
        raise SharedMapError(
            "Blockstead could not safely save squaremap's low-resource profile."
        ) from exc
    return SharedMapLowResourceResult(
        config_path=relative.as_posix(),
        backup_path=backup.relative_to(root).as_posix(),
        normal_render_threads=1,
        background_render_threads=1,
    )
