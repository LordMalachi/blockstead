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
        {ProcessState.STOPPING, ProcessState.CRASHED, ProcessState.STARTING}
    ),
    ProcessState.UNKNOWN: frozenset({ProcessState.STOPPED, ProcessState.CRASHED}),
}


@dataclass(frozen=True)
class LogEvent:
    sequence: int
    timestamp: str
    line: str


class InvalidTransition(RuntimeError):
    pass


class ProcessManager:
    def __init__(self, fake_script: Path | None = None, log_limit: int = 1000) -> None:
        self.fake_script = fake_script
        self.state = ProcessState.STOPPED
        self.exit_code: int | None = None
        self.reason = "Not started"
        self.started_at: datetime | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._force_requested = False
        self._lock = asyncio.Lock()
        self._logs: deque[LogEvent] = deque(maxlen=log_limit)
        self._subscribers: set[asyncio.Queue[LogEvent]] = set()
        self._sequence = 0

    def snapshot(self) -> dict[str, object]:
        alive = self._process is not None and self._process.returncode is None
        return {
            "state": self.state,
            "pid": self._process.pid if self._process and alive else None,
            "exit_code": self.exit_code,
            "reason": self.reason,
            "started_at": self.started_at.isoformat() if alive and self.started_at else None,
        }

    def logs(self) -> list[LogEvent]:
        return list(self._logs)

    def transition(self, target: ProcessState, reason: str) -> None:
        if target not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"Invalid process transition {self.state} -> {target}")
        self.state, self.reason = target, reason

    async def start(
        self,
        arguments: tuple[str, ...] | None = None,
        *,
        cwd: Path | None = None,
        label: str = "Server",
        mode: str = "normal",
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
                    )
                else:
                    self._process = await asyncio.create_subprocess_exec(
                        *arguments,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=cwd,
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
        while line := await process.stdout.readline():
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
        self._process.stdin.write((command + "\n").encode())
        await self._process.stdin.drain()

    async def stop(self, timeout: float = 5.0) -> bool:  # noqa: ASYNC109
        if self.state not in {ProcessState.RUNNING, ProcessState.STARTING, ProcessState.DEGRADED}:
            raise InvalidTransition("The server is not running.")
        self.transition(ProcessState.STOPPING, "Waiting for graceful shutdown")
        process = self._process
        if process is None or process.stdin is None:
            self.transition(ProcessState.CRASHED, "Process handle was unavailable")
            return False
        process.stdin.write(b"stop\n")
        await process.stdin.drain()
        try:
            await asyncio.wait_for(process.wait(), timeout)
            if self._reader:
                await self._reader
            return True
        except asyncio.TimeoutError:  # noqa: UP041
            self.reason = "The server did not stop before the timeout. Force stop is available."
            return False

    async def force_stop(self) -> None:
        if (
            self.state != ProcessState.STOPPING
            or self._process is None
            or self._process.returncode is not None
        ):
            raise InvalidTransition("Force stop is only available after a graceful stop timeout.")
        self._force_requested = True
        if os.name == "posix":
            os.killpg(self._process.pid, signal.SIGTERM)
        else:
            self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), 2.0)
        except asyncio.TimeoutError:  # noqa: UP041
            if os.name == "posix":
                os.killpg(self._process.pid, signal.SIGKILL)
            else:
                self._process.kill()
            await self._process.wait()
        if self.state == ProcessState.STOPPING:
            self.transition(ProcessState.STOPPED, "Force stopped after graceful timeout")

    async def subscribe(self, callback: Callable[[LogEvent], Awaitable[None]]) -> None:
        queue: asyncio.Queue[LogEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                await callback(await queue.get())
        finally:
            self._subscribers.discard(queue)

    async def close(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
        if self._reader:
            await asyncio.gather(self._reader, return_exceptions=True)
