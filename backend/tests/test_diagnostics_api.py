import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from blockstead import __version__

FIXTURE = Path(__file__).parents[2] / "fixtures" / "servers" / "vanilla-fixture"


def test_diagnostics_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/system/diagnostics").status_code == 401
    assert client.get("/api/v1/system/diagnostics/report").status_code == 401


def test_diagnostics_reports_software_and_settings(
    client: TestClient, auth: dict[str, str]
) -> None:
    report = client.get("/api/v1/system/diagnostics", headers=auth).json()
    assert report["report_version"] == 2
    assert report["application"]["version"] == __version__
    assert report["settings"]["bind_host"] == "127.0.0.1"
    assert report["settings"]["allowed_origins"] == ["http://testserver"]
    assert report["server"]["state"] == "STOPPED"
    assert report["host"]["memory"]["total_bytes"] > 0
    assert "network" in report
    # The startup announcement proves application logs reach the report.
    assert any("Blockstead" in entry["message"] for entry in report["recent_log"])


def test_diagnostics_captures_and_redacts_recent_errors(
    client: TestClient, auth: dict[str, str]
) -> None:
    logging.getLogger("blockstead.test_api").warning(
        "Could not read /home/alice/minecraft/server.properties"
    )
    report = client.get("/api/v1/system/diagnostics", headers=auth).json()
    matches = [
        entry
        for entry in report["recent_errors"]
        if "server.properties" in entry["message"]
    ]
    assert matches and matches[0]["level"] == "WARNING"
    assert "/home/[account]/" in matches[0]["message"]
    assert "/home/alice" not in json.dumps(report)


def test_diagnostics_report_downloads_as_a_file(
    client: TestClient, auth: dict[str, str]
) -> None:
    response = client.get("/api/v1/system/diagnostics/report", headers=auth)
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="blockstead-report-')
    assert disposition.endswith('.json"')
    assert json.loads(response.content)["report_version"] == 2


def test_diagnostics_v2_includes_safe_profile_network_evidence(
    client: TestClient, auth: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/profiles",
        headers=auth,
        json={"name": "Network fixture", "path": str(FIXTURE)},
    )
    assert created.status_code == 201

    report = client.get("/api/v1/system/diagnostics", headers=auth).json()
    network = next(
        item
        for item in report["network"]["profiles"]
        if item["profile_id"] == created.json()["id"]
    )

    assert network["directory_safety"]["state"] == "safe"
    assert network["server_properties_present"] is True
    assert network["server_port"] == 25565
    assert network["configured_bind"] is None
    assert network["enable_status"] is True
    assert "ip" not in report["network"]["public_ip"]


def test_diagnostics_compacts_repeated_errors(
    client: TestClient, auth: dict[str, str]
) -> None:
    logger = logging.getLogger("blockstead.test_api_compaction")
    for _ in range(12):
        logger.error("same bounded failure")

    report = client.get("/api/v1/system/diagnostics", headers=auth).json()
    match = next(
        entry for entry in report["recent_errors"] if entry["message"] == "same bounded failure"
    )
    assert match["occurrences"] == 12


def test_diagnostics_remain_available_when_host_uptime_is_restricted(
    client: TestClient, auth: dict[str, str], monkeypatch
) -> None:
    def denied() -> float:
        raise PermissionError("sysctl denied")

    monkeypatch.setattr("blockstead.diagnostics.psutil.boot_time", denied)
    response = client.get("/api/v1/system/diagnostics", headers=auth)

    assert response.status_code == 200
    assert response.json()["host"]["uptime_seconds"] is None
