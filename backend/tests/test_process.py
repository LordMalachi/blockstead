import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from blockstead import process as process_module
from blockstead.process import (
    CONSOLE_LINE_LIMIT,
    InvalidTransition,
    LogEvent,
    ProcessManager,
    ProcessState,
)


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
async def test_concurrent_force_stop_signals_only_one_operation() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(mode="ignore-stop")
    await wait_for(manager, ProcessState.RUNNING)
    assert await manager.stop(timeout=0.05) is False

    results = await asyncio.gather(
        manager.force_stop(),
        manager.force_stop(),
        return_exceptions=True,
    )

    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, InvalidTransition) for result in results) == 1
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_close_forces_process_only_after_graceful_timeout() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start(mode="ignore-stop")
    await wait_for(manager, ProcessState.RUNNING)

    await manager.close(timeout=0.05)

    assert manager.state == ProcessState.STOPPED
    assert manager.reason == "Force stopped after graceful timeout"


def write_script(tmp_path: Path, body: str) -> tuple[str, ...]:
    script = tmp_path / "server.py"
    script.write_text(body, encoding="utf-8")
    return (sys.executable, str(script))


@pytest.mark.asyncio
async def test_overlong_console_line_does_not_stall_the_reader(tmp_path: Path) -> None:
    arguments = write_script(
        tmp_path,
        "import sys\n"
        "print('Done (0.1s)! For help, type \"help\"', flush=True)\n"
        f"print('X' * {CONSOLE_LINE_LIMIT * 2 + 5}, flush=True)\n"
        "for i in range(2000):\n"
        "    print(f'tick {i} ' + 'y' * 100, flush=True)\n"
        "for line in sys.stdin:\n"
        "    if line.strip() == 'stop':\n"
        "        sys.exit(0)\n",
    )
    manager = ProcessManager()
    await manager.start(arguments)
    await wait_for(manager, ProcessState.RUNNING)

    async def wait_for_tail() -> None:
        while not any(event.line.startswith("tick 1999 ") for event in manager.logs()):  # noqa: ASYNC110
            await asyncio.sleep(0.01)

    await asyncio.wait_for(wait_for_tail(), 10)
    # Before the fix the reader died here, so stop timed out and even a kill hung.
    assert await asyncio.wait_for(manager.stop(timeout=5), 10) is True
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_command_after_server_closes_stdin_is_an_invalid_transition(
    tmp_path: Path,
) -> None:
    arguments = write_script(
        tmp_path,
        "import os, sys, time\n"
        "os.close(0)\n"
        "print('Done (0.1s)! For help, type \"help\"', flush=True)\n"
        "time.sleep(30)\n",
    )
    manager = ProcessManager()
    await manager.start(arguments)
    await wait_for(manager, ProcessState.RUNNING)
    try:
        with pytest.raises(InvalidTransition):
            for _ in range(50):  # the first write may land in the pipe buffer
                await manager.command("list")
                await asyncio.sleep(0.01)
    finally:
        await manager.close(timeout=0.05)
    assert manager.state == ProcessState.STOPPED


@pytest.mark.asyncio
async def test_stop_during_spawn_stops_the_new_server(monkeypatch: pytest.MonkeyPatch) -> None:
    real_spawn = asyncio.create_subprocess_exec

    async def slow_spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        await asyncio.sleep(0.2)
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(process_module.asyncio, "create_subprocess_exec", slow_spawn)
    manager = ProcessManager(fixture_script())
    starting = asyncio.create_task(manager.start())
    await asyncio.sleep(0.05)
    assert manager.state == ProcessState.STARTING

    assert await manager.stop(timeout=2) is True
    await starting
    assert manager.state == ProcessState.STOPPED
    assert manager.snapshot()["pid"] is None


@pytest.mark.asyncio
async def test_save_world_waits_for_minecraft_to_confirm() -> None:
    manager = ProcessManager(fixture_script())
    await manager.start()
    await wait_for(manager, ProcessState.RUNNING)
    try:
        assert await manager.save_world(timeout=5) is True
        assert any(event.line.endswith("Saved the game") for event in manager.logs())
    finally:
        await manager.close(timeout=1)


@pytest.mark.asyncio
async def test_save_world_ignores_chat_and_gives_up_after_the_timeout(tmp_path: Path) -> None:
    arguments = write_script(
        tmp_path,
        "import sys\n"
        "print('[Server thread/INFO]: Done (0.1s)! For help, type \"help\"', flush=True)\n"
        "for line in sys.stdin:\n"
        "    if line.strip() == 'stop':\n"
        "        sys.exit(0)\n"
        "    print('[Server thread/INFO]: <Steve> Saved the game', flush=True)\n",
    )
    manager = ProcessManager()
    await manager.start(arguments)
    await wait_for(manager, ProcessState.RUNNING)
    try:
        assert await manager.save_world(timeout=0.3) is False
    finally:
        await manager.close(timeout=1)


@pytest.mark.asyncio
async def test_replaying_subscriber_receives_every_line_exactly_once() -> None:
    manager = ProcessManager()
    for index in range(5):
        manager._publish(f"before {index}")
    received: list[int] = []

    async def consumer(event: LogEvent) -> None:
        received.append(event.sequence)
        if len(received) == 1:
            manager._publish("printed while the backlog is still being sent")
        await asyncio.sleep(0)

    task = asyncio.create_task(manager.subscribe(consumer, replay=True))
    try:

        async def wait_for_count(count: int) -> None:
            while len(received) < count:  # noqa: ASYNC110
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_count(6), 1)
        manager._publish("live")
        await asyncio.wait_for(wait_for_count(7), 1)
        assert received == [1, 2, 3, 4, 5, 6, 7]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
