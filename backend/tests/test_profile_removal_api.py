import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings
from blockstead.models import Profile

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


def test_server_root_profile_can_never_delete_managed_servers(
    removal_client: TestClient,
) -> None:
    auth = headers(removal_client)
    root = removal_client.app.state.settings.server_root
    protected = root / "family"
    protected.mkdir()
    sentinel = protected / "level.dat"
    sentinel.write_bytes(b"world")
    with removal_client.app.state.session_factory() as db:
        profile = Profile(
            name="Unsafe root import",
            server_directory=str(root),
            distribution="unknown",
            minecraft_version=None,
        )
        db.add(profile)
        db.commit()
        profile_id = profile.id

    refused = removal_client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Unsafe root import", "delete_files": True},
    )

    assert refused.status_code == 409
    assert root.is_dir()
    assert sentinel.read_bytes() == b"world"

    record_only = removal_client.request(
        "DELETE",
        f"/api/v1/profiles/{profile_id}",
        headers=auth,
        json={"confirm_name": "Unsafe root import", "delete_files": False},
    )
    assert record_only.status_code == 200
    assert root.is_dir()
    assert sentinel.read_bytes() == b"world"


def test_overlapping_profile_folders_block_file_deletion(
    removal_client: TestClient,
) -> None:
    auth = headers(removal_client)
    root = removal_client.app.state.settings.server_root
    parent = root / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    sentinel = child / "level.dat"
    sentinel.write_bytes(b"world")
    with removal_client.app.state.session_factory() as db:
        parent_profile = Profile(
            name="Parent",
            server_directory=str(parent),
            distribution="unknown",
            minecraft_version=None,
        )
        child_profile = Profile(
            name="Child",
            server_directory=str(child),
            distribution="unknown",
            minecraft_version=None,
        )
        db.add_all([parent_profile, child_profile])
        db.commit()
        parent_id = parent_profile.id
        child_id = child_profile.id

    for profile_id, name in ((parent_id, "Parent"), (child_id, "Child")):
        refused = removal_client.request(
            "DELETE",
            f"/api/v1/profiles/{profile_id}",
            headers=auth,
            json={"confirm_name": name, "delete_files": True},
        )
        assert refused.status_code == 409
        assert "overlaps" in refused.json()["error"]["message"]
        assert sentinel.read_bytes() == b"world"
