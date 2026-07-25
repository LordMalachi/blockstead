from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from blockstead.maintenance import (
    BackupPoint,
    MaintenanceContext,
    MaintenanceRequest,
    assess,
    catalog,
)

NOW = datetime(2026, 7, 24, 20, 0, tzinfo=timezone.utc)
GIB = 1024**3


def context(**overrides: object) -> MaintenanceContext:
    base = MaintenanceContext(
        profile_id="profile-1",
        profile_name="Homestead",
        distribution="fabric",
        distribution_label="Fabric",
        minecraft_version="1.21.1",
        is_fixture=False,
        state="STOPPED",
        selected_server_active=False,
        state_reason="This server is stopped.",
        online_players=None,
        max_players=20,
        last_backup=BackupPoint(id="backup-1", created_at=NOW - timedelta(hours=2), verified=True),
        disk_free_bytes=200 * GIB,
        disk_total_bytes=500 * GIB,
        world_size_bytes=2 * GIB,
        extension_signature=("fabric-api.jar@0.100.0",),
        extension_warnings=(),
        required_java_major=21,
        compatible_java_found=True,
        launch_problem=None,
        pending_restart=False,
        pending_restart_detail="",
        next_operation_label=None,
        next_operation_at=None,
        occupied_by=None,
        now=NOW,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def plan_for(change_id: str, **overrides: object):
    return assess(context(**overrides), MaintenanceRequest(change_id=change_id))


def finding(plan, finding_id: str):
    return next(item for item in plan.findings if item.id == finding_id)


def step(plan, step_id: str):
    return next(item for item in plan.steps if item.id == step_id)


def test_catalog_covers_every_reviewable_change() -> None:
    changes = catalog().changes
    assert {change.id for change in changes} == {
        "extension_update",
        "extension_install",
        "settings_change",
        "world_files",
        "server_upgrade",
    }
    # Every change that touches server or world files must be stopped-server only.
    for change in changes:
        if change.destructive or change.version_changing:
            assert change.requires_stopped_server
            assert change.restart_expectation == "required"


@pytest.mark.parametrize(
    "change_id", ["extension_update", "extension_install", "world_files", "server_upgrade"]
)
def test_risky_changes_always_require_a_protection_step(change_id: str) -> None:
    """A fresh verified backup softens the wording, never the requirement."""

    plan = plan_for(change_id)
    assert step(plan, "backup").requirement == "required"
    assert plan.restart == "required"
    assert plan.restart_detail


def test_a_clean_stopped_server_is_ready_with_an_ordered_plan() -> None:
    plan = plan_for("extension_update")
    assert plan.readiness == "ready"
    assert plan.blockers == []
    assert [item.id for item in plan.steps] == ["backup", "stop", "apply", "validate", "restart"]
    assert step(plan, "stop").requirement == "not_needed"
    assert plan.protection.verified is True


def test_a_running_server_gains_announce_save_and_stop_steps() -> None:
    plan = plan_for(
        "world_files",
        state="RUNNING",
        selected_server_active=True,
        online_players=3,
    )
    assert [item.id for item in plan.steps] == [
        "announce",
        "save",
        "backup",
        "stop",
        "apply",
        "validate",
        "restart",
    ]
    assert step(plan, "announce").requirement == "required"
    assert step(plan, "stop").requirement == "required"
    assert plan.readiness == "ready_with_warnings"
    assert finding(plan, "connected-players").status == "attention"


def test_an_unanswered_status_check_reads_as_unknown_not_empty() -> None:
    plan = plan_for(
        "world_files", state="RUNNING", selected_server_active=True, online_players=None
    )
    players = finding(plan, "connected-players")
    assert players.status == "unknown"
    assert "unknown" in players.detail
    # An unknown roster still forces the announcement rather than assuming nobody is on.
    assert step(plan, "announce").requirement == "required"
    assert plan.readiness == "ready_with_warnings"


def test_an_unverified_upgrade_source_is_never_presented_as_safe() -> None:
    plan = plan_for("server_upgrade")
    assert plan.readiness == "blocked"
    assert finding(plan, "compatibility").status == "blocked"
    assert "no verified upgrade source" in finding(plan, "compatibility").detail
    assert plan.blockers


def test_a_disk_that_cannot_hold_a_backup_blocks_the_change() -> None:
    plan = plan_for("extension_install", disk_free_bytes=1 * GIB, world_size_bytes=40 * GIB)
    assert plan.readiness == "blocked"
    assert finding(plan, "disk-space").status == "blocked"


def test_an_unmeasurable_world_is_reported_as_unknown() -> None:
    plan = plan_for("extension_install", world_size_bytes=None)
    assert finding(plan, "disk-space").status == "unknown"
    assert plan.readiness == "ready_with_warnings"


def test_a_failed_backup_verification_is_not_treated_as_protection() -> None:
    plan = plan_for(
        "world_files",
        last_backup=BackupPoint(
            id="backup-1",
            created_at=NOW - timedelta(hours=1),
            verified=False,
            problem="This backup failed checksum verification.",
        ),
    )
    assert plan.protection.verified is False
    assert finding(plan, "protection-point").status == "attention"
    assert step(plan, "backup").requirement == "required"


def test_a_missing_backup_is_stated_plainly() -> None:
    plan = plan_for("world_files", last_backup=None)
    assert plan.protection.verified is False
    assert plan.protection.backup_id is None
    assert "no completed backup" in finding(plan, "protection-point").detail


def test_a_stale_verified_backup_is_still_called_out() -> None:
    plan = plan_for("world_files", last_backup=BackupPoint(
        id="backup-1", created_at=NOW - timedelta(days=9), verified=True
    ))
    assert plan.protection.verified is True
    assert finding(plan, "protection-point").status == "attention"
    assert "days old" in finding(plan, "protection-point").detail


def test_another_running_server_blocks_the_change() -> None:
    plan = plan_for("extension_update", occupied_by="Creative build")
    assert plan.readiness == "blocked"
    assert finding(plan, "server-state").status == "blocked"


def test_a_transitional_state_blocks_the_change() -> None:
    plan = plan_for("extension_update", state="STOPPING", selected_server_active=True)
    assert plan.readiness == "blocked"
    assert finding(plan, "server-state").status == "blocked"


def test_a_broken_launch_plan_blocks_a_version_changing_change() -> None:
    plan = plan_for("extension_update", launch_problem="No server jar was found in this folder.")
    assert plan.readiness == "blocked"
    assert finding(plan, "compatibility").status == "blocked"

    reversible = plan_for(
        "settings_change", launch_problem="No server jar was found in this folder."
    )
    assert reversible.readiness == "ready_with_warnings"
    assert finding(reversible, "compatibility").status == "attention"


def test_an_unknown_java_requirement_is_reported_as_unknown() -> None:
    plan = plan_for("settings_change", required_java_major=None, compatible_java_found=None)
    assert finding(plan, "compatibility").status == "unknown"


def test_a_settings_change_does_not_demand_a_stop() -> None:
    plan = plan_for(
        "settings_change", state="RUNNING", selected_server_active=True, online_players=0
    )
    assert [item.id for item in plan.steps] == [
        "announce",
        "save",
        "backup",
        "apply",
        "restart",
    ]
    assert finding(plan, "server-state").status == "ready"
    assert plan.restart == "recommended"


def test_a_pending_restart_is_surfaced_before_stacking_another_change() -> None:
    plan = plan_for(
        "settings_change",
        state="RUNNING",
        selected_server_active=True,
        online_players=0,
        pending_restart=True,
        pending_restart_detail="A change saved after this server started is still waiting.",
    )
    assert finding(plan, "pending-restart").status == "attention"
    assert plan.readiness == "ready_with_warnings"


def test_a_scheduled_operation_due_soon_is_flagged() -> None:
    plan = plan_for(
        "world_files",
        next_operation_label="Maintenance stop",
        next_operation_at=NOW + timedelta(minutes=20),
    )
    assert finding(plan, "scheduled-operation").status == "attention"

    later = plan_for(
        "world_files",
        next_operation_label="Maintenance stop",
        next_operation_at=NOW + timedelta(hours=6),
    )
    assert finding(later, "scheduled-operation").status == "ready"


def test_the_plan_id_tracks_the_evidence_the_review_was_based_on() -> None:
    first = plan_for("extension_update")
    assert plan_for("extension_update").plan_id == first.plan_id
    # A changed extension set is a different review, so the plan is a different plan.
    changed = plan_for("extension_update", extension_signature=("fabric-api.jar@0.101.0",))
    assert changed.plan_id != first.plan_id
    # So is a different protection point.
    other_backup = plan_for(
        "extension_update",
        last_backup=BackupPoint(id="backup-2", created_at=NOW, verified=True),
    )
    assert other_backup.plan_id != first.plan_id
    # And so is a different change against identical evidence.
    assert plan_for("extension_install").plan_id != first.plan_id


def test_the_practice_server_is_labelled_rather_than_judged() -> None:
    plan = plan_for("settings_change", is_fixture=True, launch_problem=None)
    assert finding(plan, "compatibility").status == "info"
    assert "practice server" in finding(plan, "compatibility").detail
