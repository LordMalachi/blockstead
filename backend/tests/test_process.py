import asyncio
from pathlib import Path

import pytest

from blockstead.process import InvalidTransition, ProcessManager, ProcessState


async def wait_for(  # noqa: ASYNC109
    manager: ProcessManager,
    state: ProcessState,
    timeout: float = 2,  # noqa: ASYNC109
) -> None:
    async def poll() -> None:
        while manager.state != state:  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


def fixture_script() -> Path:
    return Path(__file__).parents[1] / "src" / "blockstead" / "fake_server.py"


@pytest.mark.asyncio
async def test_ready_command_and_graceful_stop() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start()
    await wait_for(manager, ProcessState.RUNNING)
    await manager.command("say hello; touch /tmp/not-executed")

    async def wait_for_command() -> None:
        while not any(  # noqa: ASYNC110
            "say hello; touch /tmp/not-executed" in event.line for event in manager.logs()
        ):
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_command(), 1)
    assert await manager.stop(timeout=1) is True
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_logs_stay_attributed_to_the_profile_that_produced_them() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(owner="profile-a")
    await wait_for(manager, ProcessState.RUNNING)
    await manager.stop(timeout=1)
    first_run = [event.sequence for event in manager.logs()]
    assert first_run, "the first run should have produced log lines"

    # The rolling buffer outlives the run, so a second profile must not inherit it.
    await manager.start(owner="profile-b")
    await wait_for(manager, ProcessState.RUNNING)
    await manager.stop(timeout=1)

    events = manager.logs()
    assert {event.profile_id for event in events} == {"profile-a", "profile-b"}
    assert all(event.profile_id == "profile-a" for event in events if event.sequence in first_run)
    assert [event for event in events if event.profile_id == "profile-b"]


@pytest.mark.asyncio
async def test_duplicate_start_fails_safely() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start()
    with pytest.raises(InvalidTransition):
        await manager.start()
    await manager.close(timeout=1)
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_abnormal_exit_becomes_crashed() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(mode="crash")
    await wait_for(manager, ProcessState.CRASHED)
    assert manager.exit_code == 17


@pytest.mark.asyncio
async def test_stop_timeout_requires_explicit_force() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(mode="ignore-stop")
    await wait_for(manager, ProcessState.RUNNING)
    assert await manager.stop(timeout=0.05) is False
    assert manager.state == ProcessState.STOPPING
    await manager.force_stop()
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_close_forces_process_only_after_graceful_timeout() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(mode="ignore-stop")
    await wait_for(manager, ProcessState.RUNNING)

    await manager.close(timeout=0.05)

    assert manager.state == ProcessState.STOPPED
    assert manager.reason == "Force stopped after graceful timeout"
