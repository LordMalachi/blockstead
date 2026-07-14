import json
import tomllib
from pathlib import Path

from blockstead import __version__


def test_release_versions_stay_in_sync() -> None:
    root = Path(__file__).parents[2]
    with (root / "backend" / "pyproject.toml").open("rb") as handle:
        backend_version = tomllib.load(handle)["project"]["version"]
    with (root / "frontend" / "package.json").open(encoding="utf-8") as handle:
        frontend_version = json.load(handle)["version"]

    assert __version__ == backend_version == frontend_version
