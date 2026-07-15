from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from blockstead.app import SpaStaticFiles


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
