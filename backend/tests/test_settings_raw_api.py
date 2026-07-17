from pathlib import Path

from test_settings_api import editable_client

SECRET_FILE = (
    "# family server\n"  # noqa: S105  # deliberately fake test credential
    "motd=Home server\n"
    "max-players=20\n"
    "rcon.password=hunter2\n"
    "custom-key=preserved\n"
)


def write_properties(server: Path, content: str = SECRET_FILE) -> None:
    (server / "server.properties").write_text(content, encoding="utf-8")


def test_raw_view_hides_secret_values(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()

        assert view["present"] is True and view["editable"] is True
        assert "hunter2" not in view["content"]
        assert "rcon.password=••••••••" in view["content"]
        assert view["secret_keys"] == ["rcon.password"]
        assert "motd=Home server" in view["content"]
        guided = client.get(f"/api/v1/profiles/{profile_id}/settings", headers=auth).json()
        assert view["revision"] == guided["revision"]
    finally:
        client.__exit__(None, None, None)


def test_raw_preview_reports_problems_with_line_numbers(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()
        broken = (
            "this line has no equals sign\n"
            "max-players=-5\n"
            "motd=first\n"
            "motd=second\n"
        )
        preview = client.post(
            f"/api/v1/profiles/{profile_id}/settings/raw/preview",
            headers=auth,
            json={"revision": view["revision"], "content": broken},
        ).json()

        assert preview["valid"] is False
        assert any("Line 1" in problem for problem in preview["problems"])
        assert any(
            "Line 2" in problem and "at least 1" in problem for problem in preview["problems"]
        )
        assert any(
            "Line 4" in problem and "repeats" in problem for problem in preview["problems"]
        )
    finally:
        client.__exit__(None, None, None)


def test_raw_preview_summarizes_changes(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()
        edited = view["content"].replace("motd=Home server", "motd=Neighbors welcome")
        edited = edited.replace("custom-key=preserved", "custom-key=changed")
        edited = edited.replace("max-players=20\n", "")
        preview = client.post(
            f"/api/v1/profiles/{profile_id}/settings/raw/preview",
            headers=auth,
            json={"revision": view["revision"], "content": edited},
        ).json()

        assert preview["valid"] is True
        assert preview["no_changes"] is False
        assert [change["key"] for change in preview["changed_known"]] == ["motd"]
        assert preview["removed_known"] == ["max-players"]
        assert preview["other_lines_changed"] is True
        assert preview["restart_required"] is True
    finally:
        client.__exit__(None, None, None)


def test_raw_apply_restores_secrets_and_creates_recovery_copy(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()
        edited = view["content"].replace("motd=Home server", "motd=Neighbors welcome")

        response = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": edited},
        )

        assert response.status_code == 200
        result = response.json()
        written = (server / "server.properties").read_text(encoding="utf-8")
        assert "motd=Neighbors welcome" in written
        assert "rcon.password=hunter2" in written
        assert "••••" not in written
        snapshots = list(
            (client.app.state.settings.data_dir / "settings-snapshots" / profile_id).iterdir()
        )
        assert [snapshot.name for snapshot in snapshots] == [result["snapshot_name"]]
        assert snapshots[0].read_text(encoding="utf-8") == SECRET_FILE
        assert result["view"]["revision"] == result["revision"]
        again = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()
        assert "rcon.password=••••••••" in again["content"]
    finally:
        client.__exit__(None, None, None)


def test_raw_apply_refuses_invalid_content_and_stale_revision(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        original = (server / "server.properties").read_bytes()
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()

        invalid = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": "difficulty=impossible\n"},
        )
        assert invalid.status_code == 422
        assert (server / "server.properties").read_bytes() == original

        unchanged = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": view["content"]},
        )
        assert unchanged.status_code == 422
        assert "Nothing changed" in unchanged.json()["error"]["message"]

        stale = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": "0" * 64, "content": view["content"] + "pvp=true\n"},
        )
        assert stale.status_code == 409
        assert (server / "server.properties").read_bytes() == original
    finally:
        client.__exit__(None, None, None)


VANILLA_FILE = (
    "#Minecraft server properties\n"
    "#Mon Jul 17 09:00:00 EDT 2026\n"
    "enable-jmx-monitoring=false\n"
    "rcon.port=25575\n"
    "level-seed=\n"
    "gamemode=survival\n"
    "generator-settings={}\n"
    "enforce-secure-profile=true\n"
    "level-name=world\n"
    "motd=\\u00A7aA Minecraft Server\n"
    "query.port=25565\n"
    "pvp=true\n"
    "rcon.password=\n"
    "max-players=20\n"
)


def test_raw_editor_round_trips_a_real_vanilla_file(tmp_path: Path) -> None:
    """A file exactly as the vanilla server writes it: timestamp comments,
    unicode escapes, empty values, and JSON-valued keys must survive."""

    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server, VANILLA_FILE)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()

        assert view["editable"] is True
        # An empty rcon.password holds no secret, so the line stays visible.
        assert view["secret_keys"] == []
        assert view["content"] == VANILLA_FILE

        preview = client.post(
            f"/api/v1/profiles/{profile_id}/settings/raw/preview",
            headers=auth,
            json={"revision": view["revision"], "content": view["content"]},
        ).json()
        assert preview["valid"] is True and preview["no_changes"] is True

        edited = view["content"].replace("pvp=true", "pvp=false")
        response = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": edited},
        )
        assert response.status_code == 200
        written = (server / "server.properties").read_text(encoding="utf-8")
        assert written == VANILLA_FILE.replace("pvp=true", "pvp=false")
    finally:
        client.__exit__(None, None, None)


def test_raw_apply_handles_new_and_unavailable_secret_values(tmp_path: Path) -> None:
    client, auth, profile_id, server = editable_client(tmp_path)
    try:
        write_properties(server)
        view = client.get(f"/api/v1/profiles/{profile_id}/settings/raw", headers=auth).json()

        orphan = view["content"] + "api-token=••••••••\n"
        refused = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": orphan},
        )
        assert refused.status_code == 422
        assert "api-token" in refused.json()["error"]["message"]

        rotated = view["content"].replace("rcon.password=••••••••", "rcon.password=new-secret")
        response = client.put(
            f"/api/v1/profiles/{profile_id}/settings/raw",
            headers=auth,
            json={"revision": view["revision"], "content": rotated},
        )
        assert response.status_code == 200
        written = (server / "server.properties").read_text(encoding="utf-8")
        assert "rcon.password=new-secret" in written
    finally:
        client.__exit__(None, None, None)
