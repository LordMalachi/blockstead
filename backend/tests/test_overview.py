import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from blockstead.models import Profile
from blockstead.overview import (
    PublicIpDiscovery,
    join_details,
    minecraft_status,
    minecraft_status_probe,
    read_properties,
    status_protocol_enabled,
    strict_world_size,
    world_size,
)
from blockstead.performance import parse_paper_mspt, parse_paper_tps

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
    assert body["join"]["host"] != "testserver"
    assert body["join"]["port"] == 25565
    assert body["join"]["address"] != "testserver:25565"
    assert body["join"]["public"] == {
        "state": "unavailable",
        "detected_ip": None,
        "server_port": 25565,
        "address": None,
        "detail": (
            "Blockstead could not detect this network's public IP. "
            "No public Minecraft address is being shown."
        ),
    }
    assert body["players"] == {
        "online": None,
        "max": 20,
        "sample": [],
        "available": False,
        "status_outcome": "not_running",
        "status_detail": "Player and server-list status is checked while this server is running.",
    }
    assert body["metrics"]["current"]["world_size_bytes"] > 0
    assert len(body["metrics"]["history"]) == 1
    assert body["last_backup"] is None
    assert body["next_operation"] is None
    assert "backup-missing" in {warning["code"] for warning in body["warnings"]}
    assert body["capabilities"]["tps"] is False
    assert body["capabilities"]["mspt"] is False
    assert body["performance"]["state"] == "unsupported"
    assert body["performance"]["available"] is False

    # Refreshing faster than the sampling interval does not manufacture a trend.
    refreshed = client.get(f"/api/v1/profiles/{profile_id}/overview").json()
    assert len(refreshed["metrics"]["history"]) == 1


def test_paper_performance_parser_accepts_only_labelled_windows() -> None:
    tps = parse_paper_tps("[Server thread/INFO]: TPS from last 1m, 5m, 15m: *20.0, 19.98, 19.95")
    mspt = parse_paper_mspt("[Server thread/INFO]: MSPT from last 5s, 10s, 60s: 2.0, 2.5, 3.0")

    assert tps == {"one_minute": 20.0, "five_minutes": 19.98, "fifteen_minutes": 19.95}
    assert mspt == {"five_seconds": 2.0, "ten_seconds": 2.5, "sixty_seconds": 3.0}
    assert parse_paper_tps("A plugin reported TPS: 20.0") is None
    assert parse_paper_mspt("A plugin reported MSPT: 3.0") is None


def test_paper_overview_collects_bounded_console_evidence(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    with client.app.state.session_factory() as db:
        profile = db.get(Profile, profile_id)
        assert profile is not None
        # The fixture controller is owned by Blockstead, so it can safely stand
        # in for a Paper process without requiring Java in an offline test.
        profile.distribution = "paper"
        db.commit()

    started = client.post("/api/v1/server/start", headers=auth, json={"profile_id": profile_id})
    assert started.status_code == 202
    for _ in range(100):
        if client.get("/api/v1/server/state").json()["state"] == "RUNNING":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Fixture did not reach RUNNING")

    body = client.get(f"/api/v1/profiles/{profile_id}/overview").json()

    assert body["capabilities"] == {"tps": True, "mspt": True, "distribution_label": "Paper"}
    assert body["performance"]["state"] == "available"
    assert body["performance"]["source"] == "Paper console /tps and /mspt commands"
    assert body["performance"]["sampling_period_seconds"] == 60
    assert body["performance"]["tps"]["one_minute"] == 20.0
    assert body["performance"]["mspt"]["five_seconds"] == 2.0


def test_paper_diagnostic_capture_is_bounded_private_and_downloadable(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    with client.app.state.session_factory() as db:
        profile = db.get(Profile, profile_id)
        assert profile is not None
        profile.distribution = "paper"
        db.commit()

    started = client.post("/api/v1/server/start", headers=auth, json={"profile_id": profile_id})
    assert started.status_code == 202
    for _ in range(100):
        if client.get("/api/v1/server/state").json()["state"] == "RUNNING":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Fixture did not reach RUNNING")

    captured = client.post(
        f"/api/v1/profiles/{profile_id}/diagnostic-captures",
        headers=auth,
        json={"duration_seconds": 1},
    )

    assert captured.status_code == 201, captured.text
    body = captured.json()
    assert body["status"] == "completed"
    assert body["output_available"] is True
    assert body["download_url"] is not None
    downloaded = client.get(body["download_url"])
    assert downloaded.status_code == 200
    assert "no viewer upload was requested" in downloaded.text
    history = client.get(f"/api/v1/profiles/{profile_id}/diagnostic-captures").json()
    assert history[0]["id"] == body["id"]
    commands = [event["line"] for event in client.get("/api/v1/server/logs").json()]
    assert any("spark profiler start" in line for line in commands)
    assert any("spark profiler stop --save-to-file" in line for line in commands)


def test_world_care_reports_storage_and_recovery_evidence(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    backup = client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth)
    assert backup.status_code == 201
    snapshot_root = client.app.state.settings.data_dir / "settings-snapshots" / profile_id
    snapshot_root.mkdir(parents=True)
    (snapshot_root / "server.properties.1").write_text("level-name=world\n", encoding="utf-8")

    response = client.get(f"/api/v1/profiles/{profile_id}/world-care")

    assert response.status_code == 200
    body = response.json()
    assert body["world_size_bytes"] > 0
    assert body["worlds"][0]["name"] == "world"
    assert body["disk"]["state"] == "available"
    assert body["last_verified_backup"]["status"] == "completed"
    assert body["backup_destinations"][0]["stored_bytes"] > 0
    assert body["recovery"]["total_bytes"] > 0
    assert body["cleanup"]["available"] is True


def test_overview_includes_backup_schedule_and_recent_profile_activity(
    client: TestClient, auth: dict[str, str]
) -> None:
    profile_id = import_fixture(client, auth)
    assert client.post(f"/api/v1/profiles/{profile_id}/backups", headers=auth).status_code == 201
    assert (
        client.put(
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
        ).status_code
        == 200
    )

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
        {"server-ip": "127.0.0.1", "server-port": "25570"},
        {"available": True, "ip": "8.8.8.8", "detail": "Public IP found."},
    )
    assert details["address"] == "127.0.0.1:25570"
    assert details["candidate_hosts"] == []
    assert details["local_only"] is True
    assert details["public"]["state"] == "local_only"


def test_join_details_never_claims_a_public_port_from_configuration() -> None:
    details = join_details(
        {"server-ip": "", "server-port": "25565"},
        {"available": True, "ip": "8.8.8.8", "detail": "Public IP found."},
    )

    assert details["port"] == 25565
    assert details["public"] == {
        "state": "port_unverified",
        "detected_ip": "8.8.8.8",
        "server_port": 25565,
        "address": None,
        "detail": "Public IP found.",
    }


async def test_public_ip_discovery_accepts_only_global_addresses_and_caches() -> None:
    requests = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"ip": "8.8.8.8"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        discovery = PublicIpDiscovery(client)
        first = await discovery.discover()
        second = await discovery.discover()

    assert first == second
    assert first["available"] is True
    assert first["ip"] == "8.8.8.8"
    assert first["outcome"] == "detected"
    assert isinstance(first["checked_at"], str)
    assert first["detail"] == (
        "Blockstead detected this network's public IP. It cannot verify the "
        "router-facing Minecraft port from inside the network."
    )
    assert requests == 1


async def test_public_ip_discovery_refuses_private_or_invalid_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ip": "192.168.1.8"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PublicIpDiscovery(client).discover()

    assert result["available"] is False
    assert result["ip"] is None
    assert result["outcome"] == "invalid_response"


def test_public_ip_refresh_uses_an_explicit_retry(client: TestClient, auth: dict[str, str]) -> None:
    profile_id = import_fixture(client, auth)
    calls: list[bool] = []

    class Discovery:
        async def discover(self, *, force: bool = False) -> dict[str, object]:
            calls.append(force)
            return {"available": True, "ip": "8.8.8.8", "detail": "Public IP found."}

    client.app.state.public_ip_discovery = Discovery()
    response = client.post(f"/api/v1/profiles/{profile_id}/connection/refresh", headers=auth)

    assert response.status_code == 200
    assert calls == [True]
    assert response.json()["public"]["state"] == "port_unverified"


def test_world_size_uses_configured_world_name_and_ignores_links(tmp_path: Path) -> None:
    (tmp_path / "server.properties").write_text("level-name=survival\n", encoding="utf-8")
    world = tmp_path / "survival"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world-data")
    (world / "linked").symlink_to(world / "level.dat")

    assert read_properties(tmp_path)["level-name"] == "survival"
    assert world_size(tmp_path) == len(b"world-data")


def test_strict_world_size_refuses_a_partial_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A safety estimate must not silently shrink when a file cannot be read."""

    (tmp_path / "server.properties").write_text("level-name=survival\n", encoding="utf-8")
    world = tmp_path / "survival"
    world.mkdir()
    (world / "level.dat").write_bytes(b"world-data")
    (world / "region.mca").write_bytes(b"x" * 64)

    real_stat = Path.stat

    def flaky_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self.name == "region.mca":
            raise OSError("file replaced while the server was running")
        return real_stat(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "stat", flaky_stat)

    # The overview still produces a number it can display...
    lenient = world_size(tmp_path)
    assert lenient is not None
    assert lenient < len(b"world-data") + 64
    # ...but the maintenance preflight refuses to guess, because a safety
    # estimate that quietly shrinks would report that a backup fits.
    assert strict_world_size(tmp_path) is None


def encode_varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


async def test_minecraft_status_reads_player_capacity_and_sample(monkeypatch: Any) -> None:
    raw = json.dumps({"players": {"online": 2, "max": 20, "sample": [{"name": "Alex"}]}}).encode()
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


async def test_minecraft_status_treats_early_eof_as_optional_status_unavailable(
    monkeypatch: Any,
) -> None:
    reader = asyncio.StreamReader()
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
    probe = await minecraft_status_probe({"server-ip": "", "server-port": "25565"})

    assert probe["outcome"] == "closed_early"
    assert probe["tcp_connected"] is True
    assert probe["status"] is None
    assert await minecraft_status({"server-ip": "", "server-port": "25565"}) is None


async def test_minecraft_status_does_not_probe_when_status_is_disabled(
    monkeypatch: Any,
) -> None:
    async def unexpected_connect(_: str, __: int) -> tuple[asyncio.StreamReader, Any]:
        raise AssertionError("status-disabled servers must not be probed")

    monkeypatch.setattr(asyncio, "open_connection", unexpected_connect)
    values = {"server-ip": "", "server-port": "25565", "enable-status": "false"}
    probe = await minecraft_status_probe(values)

    assert status_protocol_enabled(values) is False
    assert probe["outcome"] == "disabled"
    assert probe["tcp_connected"] is None
    assert probe["status"] is None
