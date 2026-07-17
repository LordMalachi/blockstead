from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[TestClient, Path, dict[str, str], str]]:
    root = tmp_path / "servers"
    settings = Settings(
        data_dir=tmp_path / "data", server_root=root, allowed_origins="http://testserver"
    )
    with TestClient(create_app(settings)) as client:
        setup = client.post(
            "/api/v1/setup/admin",
            headers={"Origin": "http://testserver"},
            json={"username": "owner", "password": "correct horse battery staple"},
        )
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": setup.json()["csrf_token"],
        }
        folder = root / "fabric-server"
        (folder / "config").mkdir(parents=True)
        (folder / "fabric-server-launch.jar").write_bytes(b"launcher")
        (folder / "config" / "example.json").write_text(
            '{"enabled": true}\n', encoding="utf-8"
        )
        created = client.post(
            "/api/v1/profiles",
            headers=headers,
            json={"name": "Fabric", "path": str(folder)},
        )
        yield client, folder, headers, created.json()["id"]


def test_config_api_lists_reads_and_safely_updates(
    api: tuple[TestClient, Path, dict[str, str], str],
) -> None:
    client, folder, headers, profile_id = api
    listing = client.get(f"/api/v1/profiles/{profile_id}/configs")
    assert listing.status_code == 200
    assert listing.json()["files"][0]["path"] == "example.json"
    document = client.get(
        f"/api/v1/profiles/{profile_id}/configs/file", params={"path": "example.json"}
    ).json()

    updated = client.put(
        f"/api/v1/profiles/{profile_id}/configs/file",
        headers=headers,
        json={
            "path": "example.json",
            "revision": document["revision"],
            "content": '{"enabled": false}\n',
        },
    )

    assert updated.status_code == 200
    assert updated.json()["restart_required"] is True
    assert "false" in (folder / "config" / "example.json").read_text(encoding="utf-8")
    assert list((folder / ".blockstead-config-backups").glob("*.bak"))


def test_config_api_refuses_stale_update(api: tuple[TestClient, Path, dict[str, str], str]) -> None:
    client, folder, headers, profile_id = api
    document = client.get(
        f"/api/v1/profiles/{profile_id}/configs/file", params={"path": "example.json"}
    ).json()
    (folder / "config" / "example.json").write_text("{}\n", encoding="utf-8")
    response = client.put(
        f"/api/v1/profiles/{profile_id}/configs/file",
        headers=headers,
        json={**document, "content": '{"enabled": false}\n'},
    )
    assert response.status_code == 409
    assert "changed after you opened" in response.json()["error"]["message"]
