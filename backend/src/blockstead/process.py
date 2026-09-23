import asyncio
import os
import signal
import sys
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path


class ProcessState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    CRASHED = "CRASHED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


#: Longest console line kept whole. Modded servers can print mod lists or registry
#: dumps far beyond asyncio's 64 KiB default; anything longer arrives in pieces.
CONSOLE_LINE_LIMIT = 1024 * 1024

#: Console text Minecraft prints once ``save-all`` has written the world (1.13+, older).
SAVE_CONFIRMATIONS = frozenset({"Saved the game", "Saved the world"})
#: How long a flush may run before a backup proceeds without the confirmation.
SAVE_CONFIRM_TIMEOUT = 30.0
#: How long an owner-requested stop waits. Large modded worlds take well over the
#: five-second default to save, and a timeout offers Force stop mid-save.
GRACEFUL_STOP_TIMEOUT = 60.0
#: Shutdown budget when Blockstead itself exits, inside systemd's 30s TimeoutStopSec.
SHUTDOWN_STOP_TIMEOUT = 20.0


async def read_console_line(stream: asyncio.StreamReader) -> bytes:
    """Read one console line, splitting any line longer than the stream limit.

    ``StreamReader.readline`` raises on an over-limit line. That would end the
    reader: the console goes silent, nothing drains the pipe, the server blocks
    on its next write, and ``wait()`` never returns even after a kill.
    """

    try:
        return await stream.readuntil(b"\n")
    except asyncio.IncompleteReadError as exc:
        return exc.partial
    except asyncio.LimitOverrunError as exc:
        return await stream.readexactly(exc.consumed)


def signal_process_group(pid: int, signal_name: str) -> None:
    """Signal a POSIX process group without exposing POSIX-only names to Windows typing."""

    killpg = getattr(os, "killpg", None)
    requested_signal = getattr(signal, signal_name, None)
    if not callable(killpg) or requested_signal is None:
        raise RuntimeError("Process-group signaling is unavailable on this host.")
    killpg(pid, requested_signal)


TRANSITIONS: dict[ProcessState, frozenset[ProcessState]] = {
    ProcessState.STOPPED: frozenset({ProcessState.STARTING}),
    ProcessState.STARTING: frozenset(
        {ProcessState.RUNNING, ProcessState.CRASHED, ProcessState.DEGRADED, ProcessState.STOPPING}
    ),
    ProcessState.RUNNING: frozenset(
        {ProcessState.STOPPING, ProcessState.CRASHED, ProcessState.DEGRADED}
    ),
    ProcessState.STOPPING: frozenset({ProcessState.STOPPED, ProcessState.CRASHED}),
    ProcessState.CRASHED: frozenset({ProcessState.STARTING, ProcessState.STOPPED}),
    ProcessState.DEGRADED: frozenset(
        {
            ProcessState.RUNNING,
            ProcessState.STOPPING,
            ProcessState.CRASHED,
            ProcessState.STARTING,
        }
    ),
    ProcessState.UNKNOWN: frozenset({ProcessState.STOPPED, ProcessState.CRASHED}),
}


@dataclass(frozen=True)
class LogEvent:
    sequence: int
    timestamp: str
    line: str
    #: Profile that produced the line. The buffer outlives any single run, so without
    #: this a reader cannot tell whose output an old line belongs to.
    profile_id: str | None = None


class InvalidTransition(RuntimeError):
    pass


class ProcessManager:
    def __init__(self, fake_script: Path | None = None, log_limit: int = 1000) -> None:
        self.fake_script = fake_script
        self.state = ProcessState.STOPPED
        self.exit_code: int | None = None
        self.reason = "Not started"
        self.started_at: datetime | None = None
        self.state_changed_at = datetime.now(timezone.utc)  # noqa: UP017
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._force_requested = False
        self._lock = asyncio.Lock()
        self._logs: deque[LogEvent] = deque(maxlen=log_limit)
        self._subscribers: set[asyncio.Queue[LogEvent]] = set()
        self._sequence = 0
        self._owner: str | None = None

    def snapshot(self) -> dict[str, object]:
        alive = self._process is not None and self._process.returncode is None
        return {
            "state": self.state,
            "pid": self._process.pid if self._process and alive else None,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "started_at": self.started_at.isoformat() if alive and self.started_at else None,
            "profile_id": self._owner if alive else None,
        }

    def logs(self) -> list[LogEvent]:
        return list(self._logs)

    def transition(self, target: ProcessState, reason: str) -> None:
        if target not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"Invalid process transition {self.state} -> {target}")
        self.state, self.reason = target, reason
        self.state_changed_at = datetime.now(timezone.utc)  # noqa: UP017

    async def start(
        self,
        arguments: tuple[str, ...] | None = None,
        *,
        cwd: Path | None = None,
        label: str = "Server",
        mode: str = "normal",
        owner: str | None = None,
    ) -> None:
        async with self._lock:
            if self.state not in {
                ProcessState.STOPPED,
                ProcessState.CRASHED,
                ProcessState.DEGRADED,
            }:
                raise InvalidTransition("The server is already starting or running.")
            self.transition(ProcessState.STARTING, "Waiting for readiness")
            self.exit_code = None
            self._force_requested = False
            self._owner = owner
            try:
                if arguments is None:
                    if self.fake_script is None:
                        raise ValueError("No server launch command was provided.")
                    arguments = (sys.executable, str(self.fake_script), "--mode", mode)
                if os.name == "posix":
                    self._process = await asyncio.create_subprocess_exec(
                        *arguments,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        start_new_session=True,
                        cwd=cwd,
                        limit=CONSOLE_LINE_LIMIT,
                    )
                else:
                    self._process = await asyncio.create_subprocess_exec(
                        *arguments,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=cwd,
                        limit=CONSOLE_LINE_LIMIT,
                    )
            except (OSError, ValueError) as exc:
                self.transition(
                    ProcessState.CRASHED, f"{label} process could not start: {type(exc).__name__}"
                )
                raise
            self.started_at = datetime.now(timezone.utc)  # noqa: UP017
            self._reader = asyncio.create_task(self._read_output())

    async def _read_output(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        while line := await read_console_line(process.stdout):
            clean = line.decode("utf-8", errors="replace").rstrip("\r\n")
            self._publish(clean)
            if "Done (" in clean and self.state == ProcessState.STARTING:
                self.transition(ProcessState.RUNNING, "Server reported ready")
        code = await process.wait()
        self.exit_code = code
        if self.state == ProcessState.STOPPING and (code == 0 or self._force_requested):
            reason = (
                "Force stopped after graceful timeout"
                if self._force_requested
                else "Stopped gracefully"
            )
            self.transition(ProcessState.STOPPED, reason)
        elif self.state in {ProcessState.STARTING, ProcessState.RUNNING, ProcessState.STOPPING}:
            self.transition(ProcessState.CRASHED, f"Process exited unexpectedly with code {code}")

    def _publish(self, line: str) -> None:
        self._sequence += 1
        event = LogEvent(
            self._sequence,
            datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            line,
            self._owner,
        )
        self._logs.append(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def command(self, command: str) -> None:
        if self.state != ProcessState.RUNNING or not self._process or not self._process.stdin:
            raise InvalidTransition("The server must be running before sending a command.")
        if (
            any(character in command for character in "\r\n\x00")
            or not command.strip()
            or len(command) > 32767
        ):
            raise ValueError("Command must be one non-empty line of at most 32,767 characters.")
        try:
            self._process.stdin.write((command + "\n").encode())
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise InvalidTransition("The server stopped before the command was sent.") from exc

    async def save_world(self, timeout: float = SAVE_CONFIRM_TIMEOUT) -> bool:  # noqa: ASYNC109
        """Run ``save-all flush`` and wait until Minecraft reports the world is on disk.

        ``command`` returns once the line reaches stdin, before the server thread has
        started saving, so archiving straight after can copy region files mid-write.
        Returns False when no confirmation arrived in time or the server went away.
        """

        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        try:
            await self.command("save-all flush")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while self.state == ProcessState.RUNNING:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return False
                try:
                    event = await asyncio.wait_for(queue.get(), min(remaining, 0.5))
                except TimeoutError:
                    continue
                # Compare the message after the log prefix so chat cannot fake it.
                if event.line.rsplit("]: ", 1)[-1].strip() in SAVE_CONFIRMATIONS:
                    return True
            return False
        finally:
            self._subscribers.discard(queue)

    async def stop(self, timeout: float = 5.0) -> bool:  # noqa: ASYNC109
        # The lock keeps a stop from landing while start() is still spawning, which
        # would signal the previous run's handle and leave the new server unowned.
        async with self._lock:
            if self.state not in {
                ProcessState.RUNNING,
                ProcessState.STARTING,
                ProcessState.DEGRADED,
            }:
                raise InvalidTransition("The server is not running.")
            self.transition(ProcessState.STOPPING, "Waiting for graceful shutdown")
            process = self._process
            if process is None or process.stdin is None:
                self.transition(ProcessState.CRASHED, "Process handle was unavailable")
                return False
            try:
                process.stdin.write(b"stop\n")
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Already exiting; the reader records how it ended.
        try:
            await asyncio.wait_for(process.wait(), timeout)
            if self._reader:
                await self._reader
            return True
        except asyncio.TimeoutError:  # noqa: UP041
            self.reason = "The server did not stop before the timeout. Force stop is available."
            return False

    async def force_stop(self) -> None:
        async with self._lock:
            if (
                self.state != ProcessState.STOPPING
                or self._process is None
                or self._process.returncode is not None
            ):
                raise InvalidTransition(
                    "Force stop is only available after a graceful stop timeout."
                )
            process = self._process
            self._force_requested = True
            try:
                if os.name == "posix":
                    signal_process_group(process.pid, "SIGTERM")
                else:
                    process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 2.0)
            except TimeoutError:
                try:
                    if os.name == "posix":
                        signal_process_group(process.pid, "SIGKILL")
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
            if self.state == ProcessState.STOPPING:
                self.transition(ProcessState.STOPPED, "Force stopped after graceful timeout")

    async def subscribe(
        self, callback: Callable[[LogEvent], Awaitable[None]], *, replay: bool = False
    ) -> None:
        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        # Snapshotting in the same step as registering means every line lands in
        # exactly one of the backlog or the queue, however long the replay takes.
        backlog = list(self._logs) if replay else []
        try:
            for event in backlog:
                await callback(event)
            while True:
                await callback(await queue.get())
        finally:
            self._subscribers.discard(queue)

    async def close(self, timeout: float = 10.0) -> None:  # noqa: ASYNC109
        if self._process and self._process.returncode is None:
            if self.state in {
                ProcessState.RUNNING,
                ProcessState.STARTING,
                ProcessState.DEGRADED,
            }:
                if not await self.stop(timeout):
                    await self.force_stop()
            elif self.state == ProcessState.STOPPING:
                try:
                    await asyncio.wait_for(self._process.wait(), timeout)
                except asyncio.TimeoutError:  # noqa: UP041
                    await self.force_stop()
            else:
                self._process.kill()
                await self._process.wait()
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)
