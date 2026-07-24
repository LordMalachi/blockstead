from blockstead.server_files import PlayerEntry, PlayerFile, PlayersView
from blockstead.troubleshooting import (
    TroubleshootingContext,
    TroubleshootingRequest,
    assess,
    catalog,
)


def context(**changes: object) -> TroubleshootingContext:
    values: dict[str, object] = {
        "profile_id": "profile-1",
        "profile_name": "Family",
        "distribution": "paper",
        "minecraft_version": "1.21.1",
        "state": "RUNNING",
        "selected_server_active": True,
        "state_reason": "Ready",
        "properties": {
            "white-list": "true",
            "server-ip": "",
            "server-port": "25565",
        },
        "players": PlayersView(
            allowlist=PlayerFile(
                present=True,
                readable=True,
                players=[PlayerEntry(name="Alex")],
            ),
            operators=PlayerFile(present=True, readable=True, players=[]),
            bans=PlayerFile(present=True, readable=True, players=[]),
        ),
        "local_status_responded": True,
        "join": {
            "address": "192.168.1.5:25565",
            "bind_address": None,
            "local_only": False,
            "public": {
                "state": "port_unverified",
                "detected_ip": "203.0.113.10",
            },
        },
        "eula_accepted": True,
        "required_java_major": 21,
        "compatible_java_found": True,
        "launch_problem": None,
        "disk_percent": 40.0,
        "memory_percent": 45.0,
        "cpu_percent": 20.0,
        "recent_errors": [],
    }
    values.update(changes)
    return TroubleshootingContext(**values)  # type: ignore[arg-type]


def test_catalog_is_versioned_and_contains_fixed_problem_choices() -> None:
    result = catalog()

    assert result.version == "2026.07.1"
    assert {problem.id for problem in result.problems} == {
        "player_cannot_join",
        "local_connection",
        "public_connection",
        "server_wont_start",
        "timeouts_or_lag",
    }
    assert all(source.checked_at == "2026-07-23" for source in result.sources)


def test_missing_allowlist_player_is_a_confirmed_problem_with_bounded_repair() -> None:
    result = assess(
        TroubleshootingRequest(problem_id="player_cannot_join", player_name="Steve"),
        context(),
    )

    assert result.outcome == "problem_found"
    allowlist = next(check for check in result.checks if check.id == "allowlist")
    assert allowlist.status == "flagged"
    assert allowlist.certainty == "confirmed"
    action = next(action for action in result.actions if action.id == "allowlist_add")
    assert action.available is True
    assert action.destructive is False
    assert "Steve" in action.confirmation


def test_player_access_passes_when_allowlist_and_ban_checks_pass() -> None:
    result = assess(
        TroubleshootingRequest(problem_id="player_cannot_join", player_name="Alex"),
        context(),
    )

    assert result.outcome == "no_problem_found"
    assert result.actions == []


def test_loopback_bind_is_confirmed_but_repair_waits_for_server_stop() -> None:
    running = assess(
        TroubleshootingRequest(problem_id="local_connection"),
        context(
            properties={"server-ip": "127.0.0.1", "server-port": "25565"},
            join={
                "address": "127.0.0.1:25565",
                "bind_address": "127.0.0.1",
                "local_only": True,
                "public": {"state": "local_only", "detected_ip": None},
            },
        ),
    )

    assert running.outcome == "problem_found"
    action = next(action for action in running.actions if action.id == "enable_lan")
    assert action.available is False
    assert action.blockers == ["Stop this server before changing its network bind address."]

    stopped = assess(
        TroubleshootingRequest(problem_id="local_connection"),
        context(
            state="STOPPED",
            selected_server_active=False,
            local_status_responded=None,
            properties={"server-ip": "127.0.0.1", "server-port": "25565"},
            join={
                "address": "127.0.0.1:25565",
                "bind_address": "127.0.0.1",
                "local_only": True,
                "public": {"state": "local_only", "detected_ip": None},
            },
        ),
    )

    action = next(action for action in stopped.actions if action.id == "enable_lan")
    assert action.available is True


def test_public_connection_never_treats_local_public_ip_discovery_as_port_proof() -> None:
    result = assess(TroubleshootingRequest(problem_id="public_connection"), context())

    external = next(check for check in result.checks if check.id == "external-port")
    assert external.status == "unknown"
    assert external.certainty == "none"
    assert "cannot prove" in external.detail


def test_readiness_reports_prerequisite_failures_without_offering_unsafe_repairs() -> None:
    result = assess(
        TroubleshootingRequest(problem_id="server_wont_start"),
        context(
            state="CRASHED",
            eula_accepted=False,
            compatible_java_found=False,
            launch_problem="No server jar was found in this folder.",
            disk_percent=96.0,
            recent_errors=["UnsupportedClassVersionError"],
        ),
    )

    assert result.outcome == "problem_found"
    assert {check.id for check in result.checks if check.certainty == "confirmed"} >= {
        "eula",
        "java",
        "launch-files",
        "disk",
    }
    assert result.actions == []
