import json
import logging

from fastapi.testclient import TestClient

from blockstead import __version__


def test_diagnostics_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/system/diagnostics").status_code == 401
    assert client.get("/api/v1/system/diagnostics/report").status_code == 401


def test_diagnostics_reports_software_and_settings(
    client: TestClient, auth: dict[str, str]
) -> None:
    report = client.get("/api/v1/system/diagnostics", headers=auth).json()
    assert report["report_version"] == 1
    assert report["application"]["version"] == __version__
    assert report["settings"]["bind_host"] == "127.0.0.1"
    assert report["settings"]["allowed_origins"] == ["http://testserver"]
    assert report["server"]["state"] == "STOPPED"
    assert report["host"]["memory"]["total_bytes"] > 0
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
    assert json.loads(response.content)["report_version"] == 1
