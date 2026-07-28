"""Opt-in smoke test against the real loader publishers and a real JVM.

This suite is intentionally excluded from ordinary pull-request runs because it
downloads Minecraft and loader artifacts, executes official installers, and
starts a server. CI runs it on a schedule and through workflow_dispatch for all
supported modded distributions.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx
import pytest

from blockstead.distributions import launch_arguments
from blockstead.process import ProcessManager
from blockstead.provisioning import provision_profile
from blockstead.safe_start import plan_safe_test_start, run_safe_test_start

pytestmark = pytest.mark.skipif(
    os.environ.get("BLOCKSTEAD_REAL_LOADER_TESTS") != "1",
    reason="set BLOCKSTEAD_REAL_LOADER_TESTS=1 to run publisher-backed loader smoke tests",
)

SUPPORTED_LOADERS = {"paper", "fabric", "forge", "neoforge", "quilt"}


@pytest.mark.asyncio
@pytest.mark.real_loader
async def test_real_loader_can_be_provisioned_and_privately_started(tmp_path: Path) -> None:
    distribution = os.environ.get("BLOCKSTEAD_REAL_LOADER_DISTRIBUTION", "paper")
    minecraft_version = os.environ.get("BLOCKSTEAD_REAL_LOADER_MINECRAFT", "1.21.1")
    assert distribution in SUPPORTED_LOADERS
    java = shutil.which("java")
    assert java is not None, "the real-loader smoke test requires Java on PATH"

    server_root = tmp_path / "servers"
    server_root.mkdir()
    timeout = httpx.Timeout(connect=30, read=300, write=300, pool=30)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        provisioned = await provision_profile(
            client,
            server_root,
            f"{distribution}-smoke",
            distribution,
            minecraft_version,
            java_executable=java,
        )

    server_directory = Path(provisioned.directory)
    (server_directory / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    # Keep scheduled CI runners comfortable while still exercising the real
    # loader, libraries, server bootstrap, readiness detection, and shutdown.
    command = list(launch_arguments(distribution, server_directory, java))
    command[1:1] = ["-Xms256M", "-Xmx1024M"]
    plan = plan_safe_test_start(
        profile_id=f"real-{distribution}",
        distribution=distribution,
        server_directory=server_directory,
        process_state="STOPPED",
        java_executable=java,
        arguments=tuple(command),
    )

    result = await run_safe_test_start(
        ProcessManager(log_limit=3000),
        plan,
        ready_timeout=300,
        stop_timeout=30,
        max_evidence_lines=300,
        max_evidence_characters=60_000,
    )

    evidence = "\n".join(item.line for item in result.evidence)
    assert result.status == "passed", (
        f"{distribution} {minecraft_version} did not become ready: "
        f"{result.failure_kind}: {result.detail}\n{evidence}"
    )
    assert result.ready is True
    assert result.validation_workspace_removed is True
    assert not Path(plan.validation_directory).exists()
    assert not any(
        server_root.glob(f".{server_directory.name}.blockstead-validation-*")
    )
