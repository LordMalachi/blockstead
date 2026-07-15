from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from blockstead import app as app_module
from blockstead.app import SpaStaticFiles, resolve_static_dir


def make_dist(root: Path) -> Path:
    dist = root / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Blockstead</title>", "utf-8")
    return dist


def test_installed_release_finds_the_dashboard_beside_the_virtual_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reproduce what install-linux.sh builds: the backend installed into
    # /opt/blockstead/venv, the dashboard copied to /opt/blockstead/frontend/dist, and
    # the service started from /opt/blockstead. A path relative to the installed module
    # lands in the virtual environment and never reaches the dashboard.
    app_dir = tmp_path / "opt" / "blockstead"
    installed = app_dir / "venv" / "lib" / "python3.12" / "site-packages" / "blockstead"
    installed.mkdir(parents=True)
    monkeypatch.setattr(app_module, "__file__", str(installed / "app.py"))
    dist = make_dist(app_dir)
    monkeypatch.chdir(app_dir)

    assert resolve_static_dir() == dist


def test_source_checkout_still_serves_its_own_build() -> None:
    # backend/src/blockstead/app.py -> repository root.
    expected = Path(app_module.__file__).parents[3] / "frontend" / "dist"
    if not expected.is_dir():
        pytest.skip("frontend/dist is not built in this checkout")
    assert resolve_static_dir() == expected


def test_configured_dashboard_wins(tmp_path: Path) -> None:
    dist = make_dist(tmp_path)
    assert resolve_static_dir(dist) == dist


def test_missing_dashboard_reports_nothing_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nowhere = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "blockstead"
    nowhere.mkdir(parents=True)
    monkeypatch.setattr(app_module, "__file__", str(nowhere / "app.py"))
    monkeypatch.chdir(tmp_path)
    assert resolve_static_dir() is None


def spa_client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<!doctype html><title>Blockstead</title>", "utf-8")
    (tmp_path / "asset.js").write_text("export const ok = true;", "utf-8")
    app = FastAPI()
    app.mount("/", SpaStaticFiles(directory=tmp_path, html=True), name="frontend")
    return TestClient(app)


def test_bookmarked_server_page_loads_the_app(tmp_path: Path) -> None:
    response = spa_client(tmp_path).get("/servers/profile-1/console")
    assert response.status_code == 200
    assert "Blockstead" in response.text


def test_real_files_still_win_over_the_fallback(tmp_path: Path) -> None:
    response = spa_client(tmp_path).get("/asset.js")
    assert response.status_code == 200
    assert "export const ok" in response.text


def test_unknown_api_paths_stay_404(tmp_path: Path) -> None:
    assert spa_client(tmp_path).get("/api/v1/not-a-route").status_code == 404
