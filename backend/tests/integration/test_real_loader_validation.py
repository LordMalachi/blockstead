"""Opt-in smoke test against the real loader publishers and a real JVM.

This suite is intentionally excluded from ordinary pull-request runs because it
downloads Minecraft and loader artifacts, executes official installers, and
starts a server. CI runs it on a schedule and through workflow_dispatch for all
supported modded distributions.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import httpx
import pytest

from blockstead.command_catalog import catalog_payload
from blockstead.distributions import launch_arguments
from blockstead.extension_command_packs import active_provider_ids
from blockstead.extension_ops import create_staging_directory, promote_staged_files
from blockstead.extension_origins import load_origin_map, record_catalog_files
from blockstead.extensions import read_extensions
from blockstead.loader_migration import copy_worlds, discover_world_roots
from blockstead.modrinth import plan_install
from blockstead.process import ProcessManager
from blockstead.provisioning import download_verified_file, provision_profile
from blockstead.safe_start import plan_safe_test_start, run_safe_test_start

pytestmark = pytest.mark.skipif(
    os.environ.get("BLOCKSTEAD_REAL_LOADER_TESTS") != "1",
    reason="set BLOCKSTEAD_REAL_LOADER_TESTS=1 to run publisher-backed loader smoke tests",
)

SUPPORTED_LOADERS = {"paper", "fabric", "forge", "neoforge", "quilt"}


async def _run_server(
    distribution: str,
    directory: Path,
    java: str,
    *,
    expected_log_lines: tuple[str, ...] = (),
    commands: tuple[str, ...] = (),
) -> str:
    """Run a real server to readiness, check runtime evidence, and stop it cleanly."""
    manager = ProcessManager(log_limit=5000)
    command = list(launch_arguments(distribution, directory, java))
    command[1:1] = ["-Xms256M", "-Xmx1024M"]
    try:
        await manager.start(tuple(command), cwd=directory, label=distribution, owner=distribution)
        async with asyncio.timeout(300):
            while manager.state.value not in {"RUNNING", "CRASHED"}:  # noqa: ASYNC110
                await asyncio.sleep(0.25)
        evidence = "\n".join(item.line for item in manager.logs())
        assert manager.state.value == "RUNNING", evidence
        for command_line in commands:
            await manager.command(command_line)
        if commands:
            # Plugin command responses are emitted asynchronously by the server
            # thread, so wait for evidence rather than relying on fixed timing.
            async with asyncio.timeout(10):
                while True:  # noqa: ASYNC110
                    evidence = "\n".join(item.line for item in manager.logs())
                    if all(
                        expected.casefold() in evidence.casefold()
                        for expected in expected_log_lines
                    ):
                        break
                    await asyncio.sleep(0.1)
        for expected in expected_log_lines:
            assert expected.casefold() in evidence.casefold(), evidence
        assert await manager.stop(timeout=30), evidence
        return evidence
    finally:
        await manager.close(timeout=10)


async def _install_modrinth_project(
    client: httpx.AsyncClient,
    plugins: Path,
    minecraft_version: str,
    project_id: str,
) -> None:
    """Exercise the same verified staging and promotion path as a catalog install."""
    planned = await plan_install(client, "paper", minecraft_version, project_id)
    staging = create_staging_directory(plugins)
    try:
        for item in planned:
            assert item.checksum_algorithm is not None
            assert item.checksum is not None
            await download_verified_file(
                client,
                item.url,
                staging,
                item.file_name,
                item.checksum_algorithm,
                item.checksum,
            )
        promote_staged_files(plugins, staging, [item.file_name for item in planned])
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    record_catalog_files(plugins, "modrinth", planned)


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
    assert not Path(plan.validation_directory).exists()  # noqa: ASYNC240
    assert not any(
        server_root.glob(f".{server_directory.name}.blockstead-validation-*")
    )


@pytest.mark.asyncio
@pytest.mark.real_loader
async def test_vanilla_world_migrates_to_paper_with_catalog_plugins_and_commands(
    tmp_path: Path,
) -> None:
    """Prove the complete Vanilla -> Paper owner journey against live publishers."""
    if os.environ.get("BLOCKSTEAD_REAL_LOADER_DISTRIBUTION", "paper") != "paper":
        pytest.skip("the Vanilla migration and plugin journey is Paper-specific")
    minecraft_version = os.environ.get("BLOCKSTEAD_REAL_LOADER_MINECRAFT", "1.21.1")
    java = shutil.which("java")
    assert java is not None, "the real-loader smoke test requires Java on PATH"
    server_root = tmp_path / "migration-servers"
    server_root.mkdir()
    timeout = httpx.Timeout(connect=30, read=300, write=300, pool=30)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        vanilla = await provision_profile(
            client,
            server_root,
            "vanilla-source",
            "vanilla",
            minecraft_version,
            java_executable=java,
        )
        vanilla_directory = Path(vanilla.directory)
        (vanilla_directory / "eula.txt").write_text("eula=true\n", encoding="utf-8")
        await _run_server("vanilla", vanilla_directory, java)
        level_name, roots = discover_world_roots(vanilla_directory, "world")
        assert roots, "Vanilla did not generate a migratable world"

        paper = await provision_profile(
            client,
            server_root,
            "paper-target",
            "paper",
            minecraft_version,
            java_executable=java,
        )
        paper_directory = Path(paper.directory)
        copied = copy_worlds(
            roots,
            paper_directory,
            level_name,
            "vanilla",
            "paper",
            minecraft_version,
        )
        assert level_name in copied
        assert (paper_directory / level_name / "level.dat").is_file()

        plugins = paper_directory / "plugins"
        await _install_modrinth_project(client, plugins, minecraft_version, "essentialsx")
        await _install_modrinth_project(client, plugins, minecraft_version, "luckperms")

    (paper_directory / "eula.txt").write_text("eula=true\n", encoding="utf-8")
    evidence = await _run_server(
        "paper",
        paper_directory,
        java,
        commands=("essentials:essentials", "lp info"),
        expected_log_lines=(
            "[LuckPerms] Successfully enabled.",
            "[Essentials] Enabling Essentials",
            "/essentials:essentials reload",
            "Server Brand:",
        ),
    )
    assert "Done (" in evidence
    assert "Error initializing plugin" not in evidence
    assert "Error occurred while enabling" not in evidence
    assert (paper_directory / "plugins" / "Essentials").is_dir()
    assert (paper_directory / "plugins" / "LuckPerms").is_dir()

    view = read_extensions(paper_directory, "paper")
    origins = load_origin_map(plugins)
    providers = active_provider_ids(
        "paper",
        view.entries,
        minecraft_version,
        {name: origin.project_id for name, origin in origins.items()},
    )
    assert {"essentialsx", "luckperms"} <= providers
    command_ids = {item["id"] for item in catalog_payload(providers)["commands"]}
    assert "essentialsx_broadcast" in command_ids
    assert "luckperms_group_permission" in command_ids
