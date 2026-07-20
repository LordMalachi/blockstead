import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from blockstead.overview import join_details, minecraft_status, read_properties, world_size

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def import_fixture(client: TestClient, auth: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/profiles", headers=auth, json={"name": "Fixture", "path": str(FIXTURE)}
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_overview_reports_join_address_health_and_protection(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)

    response = client.get(f"/api/v1/profiles/{profile_id}/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["state"]["value"] == "STOPPED"
    assert body["join"]["host"] == "testserver"
    assert body["join"]["port"] == 25565
    assert body["join"]["address"] == "testserver:25565"
    assert body["players"] == {
        "online": None,
        "max": 20,
        "sample": [],
        "available": False,
    }
    assert body["metrics"]["current"]["world_size_bytes"] > 0
    assert len(body["metrics"]["history"]) == 1
    assert body["last_backup"] is None
    assert body["next_operation"] is None
    assert "backup-missing" in {warning["code"] for warning in body["warnings"]}
    assert body["capabilities"]["tps"] is False
    assert body["capabilities"]["mspt"] is False

    # Refreshing faster than the sampling interval does not manufacture a trend.
    refreshed = client.get(f"/api/v1/profiles/{profile_id}/overview").json()
    assert len(refreshed["metrics"]["history"]) == 1


def test_overview_includes_backup_schedule_and_recent_profile_activity(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    assert client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).status_code == 201
    assert client.put(
        f"/api/v1/schedules/{profile_id}",
        headers=auth,
        json={
            "profile_id": profile_id,
            "enabled": True,
            "start_time": "09:00",
            "stop_time": "22:30",
            "backup_before_stop": True,
            "power_off_after_stop": False,
            "wake_time": None,
        },
    ).status_code == 200

    body = client.get(f"/api/v1/profiles/{profile_id}/overview").json()

    assert body["last_backup"]["status"] == "completed"
    assert body["next_operation"]["label"] in {"Start server", "Maintenance stop"}
    assert "backup-missing" not in {warning["code"] for warning in body["warnings"]}
    assert [event["category"] for event in body["activity"]][:2] == [
        "schedule_update",
        "manual_backup",
    ]


def test_overview_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/profiles/not-here/overview").status_code == 401


def test_join_details_honors_explicit_bind_and_port() -> None:
    details = join_details(
        {"server-ip": "127.0.0.1", "server-port": "25570"}, "example.test"
    )
    assert details["address"] == "127.0.0.1:25570"
    assert details["candidate_hosts"] == []
    assert details["local_only"] is True


def test_world_size_uses_configured_world_name_and_ignores_links(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("level-name=survival\n", encoding="utf-8")
    world = tmp_path / "survival"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world-data")
    (world / "linked").symlink_to(world / "level.dat")

    assert read_properties(tmp_path)["level-name"] == "survival"
    assert world_size(tmp_path) == len(b"world-data")


def encode_varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


async def test_minecraft_status_reads_player_capacity_and_sample(monkeypatch: Any) -> None:
    raw = json.dumps(
        {"players": {"online": 2, "max": 20, "sample": [{"name": "Alex"}]}}
    ).encode()
    packet = b"\x00" + encode_varint(len(raw)) + raw
    reader = asyncio.StreamReader()
    reader.feed_data(encode_varint(len(packet)) + packet)
    reader.feed_eof()

    class Writer:
        def write(self, _: bytes) -> None:
            pass

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def connect(_: str, __: int) -> tuple[asyncio.StreamReader, Any]:
        return reader, Writer()

    monkeypatch.setattr(asyncio, "open_connection", connect)
    result = await minecraft_status({"server-ip": "127.0.0.1", "server-port": "25565"})

    assert result == {"online": 2, "max": 20, "sample": ["Alex"]}
