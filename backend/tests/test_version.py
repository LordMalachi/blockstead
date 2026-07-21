import json
import tomllib
from pathlib import Path

from blockstead import __version__
from blockstead.provisioning import USER_AGENT


def test_release_versions_stay_in_sync() -> None:
    root = Path(__file__).parents[2]
    with (root / "backend" / "pyproject.toml").open("rb") as handle:
        backend_version = tomllib.load(handle)["project"]["version"]
    with (root / "frontend" / "package.json").open(encoding="utf-8") as handle:
        frontend_version = json.load(handle)["version"]
    with (root / "frontend" / "package-lock.json").open(encoding="utf-8") as handle:
        frontend_lock = json.load(handle)

    assert __version__ == backend_version == frontend_version
    assert frontend_lock["version"] == __version__
    assert frontend_lock["packages"][""]["version"] == __version__
    assert USER_AGENT == (
        f"blockstead/{__version__} (https://github.com/LordMalachi/blockstead)"
    )
