from pathlib import Path

from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


def editable_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], str, Path]:
    root = tmp_path / "servers"
    server = root / "home"
    server.mkdir(parents=True)
    (server / "server.jar").write_bytes(b"fixture")
    (server / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    (server / "server.properties").write_bytes(
        b"# keep this comment\n"
        b"motd=Home server\n"
        b"max-players=20\n"
        b"white-list=true\n"
        b"enforce-whitelist=true\n"
        b"custom-key=preserved\n"
    )
    settings = Settings(
        data_dir=tmp_path / "data",
        server_root=root,
        allowed_origins="http://testserver",
    )
    client = TestClient(create_app(settings))
    client.__enter__()
    setup = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    auth = {
        "Origin": "http://testserver",
        "X-CSRF-Token": setup.json()["csrf_token"],
    }
    profile = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Home", "path": str(server)},
    )
    return client, auth, str(profile.json()["id"]), server


def test_settings_preview_and_apply_api(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        view = client.get(f"/api/v1/profiles/{profile_id}/settings").json()
        payload = {
            "revision": view["revision"],
            "changes": [
                {"key": "motd", "value": "Neighbors welcome"},
                {"key": "max-players", "value": 12},
            ],
        }

        preview = client.post(
            f"/api/v1/profiles/{profile_id}/settings/preview",
            headers=auth,
            json=payload,
        )
        assert preview.status_code == 200
        assert [change["key"] for change in preview.json()["changes"]] == [
            "motd",
            "max-players",
        ]
        assert (server / "server.properties").read_text().count("Home server") == 1

        applied = client.put(
            f"/api/v1/profiles/{profile_id}/settings",
            headers=auth,
            json=payload,
        )
        assert applied.status_code == 200
        body = applied.json()
        assert body["restart_required"] is True
        assert body["revision"] != body["previous_revision"]
        assert body["view"]["revision"] == body["revision"]
        text = (server / "server.properties").read_text(encoding="utf-8")
        assert "motd=Neighbors welcome\n" in text
        assert "max-players=12\n" in text
        assert "custom-key=preserved\n" in text
        snapshot = tmp_path / "data" / "settings-snapshots" / profile_id / body["snapshot_name"]
        assert "motd=Home server\n" in snapshot.read_text(encoding="utf-8")
    finally:
        client.__exit__(None, None, None)


def test_settings_api_rejects_stale_and_wrongly_typed_values(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        revision = client.get(f"/api/v1/profiles/{profile_id}/settings").json()["revision"]
        wrong_type = client.post(
            f"/api/v1/profiles/{profile_id}/settings/preview",
            headers=auth,
            json={
                "revision": revision,
                "changes": [{"key": "max-players", "value": "12"}],
            },
        )
        assert wrong_type.status_code == 422

        with (server / "server.properties").open("a", encoding="utf-8") as handle:
            handle.write("# changed elsewhere\n")
        stale = client.put(
            f"/api/v1/profiles/{profile_id}/settings",
            headers=auth,
            json={
                "revision": revision,
                "changes": [{"key": "max-players", "value": 12}],
            },
        )
        assert stale.status_code == 409
        assert "Reload settings" in stale.json()["error"]["message"]
    finally:
        client.__exit__(None, None, None)
