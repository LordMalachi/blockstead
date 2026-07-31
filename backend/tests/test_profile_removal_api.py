import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


@pytest.fixture
def removal_client(tmp_path: Path) -> Iterator[TestClient]:
    root = tmp_path / "servers"
    root.mkdir()
    with TestClient(
        create_app(
            Settings(
                data_dir=tmp_path / "data",
                server_root=root,
                allowed_origins="http://testserver",
            )
        )
    ) as client:
        yield client


def headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}


def imported_server(client: TestClient, auth: dict[str, str], root: Path) -> tuple[str, Path]:
    directory = root / "family"
    shutil.copytree(FIXTURE, directory)
    created = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Family", "path": str(directory)}
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"]), directory


def test_removing_a_profile_keeps_the_server_and_backups(
    removal_client: TestClient,
) -> None:
    auth = headers(removal_client)
    root = removal_client.app.state.settings.server_root
    profile_id, directory = imported_server(removal_client, auth, root)
    backup = removal_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)
    assert backup.status_code == 201, backup.text

    removed = removal_client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Family", "delete_files": False},
    )

    assert removed.status_code == 200, removed.text
    assert removed.json()["files_deleted"] is False
    assert directory.is_dir()
    assert (removal_client.app.state.settings.data_dir / "backups" / profile_id).is_dir()
    assert removal_client.get("/api/v1/profiles", headers=auth).json() == []


def test_permanent_removal_requires_the_exact_name_and_deletes_local_data(
    removal_client: TestClient,
) -> None:
    auth = headers(removal_client)
    root = removal_client.app.state.settings.server_root
    profile_id, directory = imported_server(removal_client, auth, root)
    backup = removal_client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)
    assert backup.status_code == 201

    refused = removal_client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Wrong", "delete_files": True},
    )
    assert refused.status_code == 422
    assert directory.is_dir()

    removed = removal_client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Family", "delete_files": True},
    )

    assert removed.status_code == 200, removed.text
    assert removed.json()["files_deleted"] is True
    assert not directory.exists()
    assert not (removal_client.app.state.settings.data_dir / "backups" / profile_id).exists()
