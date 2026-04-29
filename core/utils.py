"""
Domain-agnostic async utilities.
"""

import asyncio
import contextlib
import json
import os
import re
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

# Move type alias here to avoid circular imports from schemas.py
AsyncValidator = Callable[[httpx.Response], Awaitable[bool]]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", text.lower()).strip("_")
    return re.sub(r"_+", "_", slug) or "default_role"


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    CRASHED = "crashed"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"


class ServiceError(Exception):
    """Base exception for service operations."""


class CommandError(ServiceError):
    """Raised when a shell command fails."""

    def __init__(self, returncode: int, stdout: str, stderr: str, cmd: Sequence[str]):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(f"Command '{' '.join(cmd)}' failed with exit code {returncode}")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    cmd: Sequence[str]


def parse_cli_json(stdout: str) -> dict[str, Any] | list[Any]:
    """Robustly extract and parse a JSON object or array from CLI stdout (ignoring preambles/warnings)."""

    match = re.search(r"(\{.*\}|\[.*\])", stdout, re.DOTALL)
    if not match:
        raise ValueError("Could not find a JSON object in the command output.")

    json_str = match.group(0)

    if stdout.strip() != json_str:
        logger.warning(
            "parse_cli_json encountered non-JSON text in output where only JSON was expected."
        )

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Found JSON-like structure but failed to parse: {e}") from e


async def async_run_command(
    cmd: Sequence[str],
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    capture_output: bool = True,
    stream_output: bool = False,
) -> CommandResult:
    """Run a shell command asynchronously."""
    cwd_path = Path(cwd) if cwd else Path.cwd()
    cmd_str = [str(c) for c in cmd]

    logger.debug(f"Running command: {' '.join(cmd_str)} (cwd: {cwd_path})")

    # If stream_output is True, pipe stdout and stderr to the process's standard streams instead of capturing
    stdout_dest = (
        sys.stdout if stream_output else (asyncio.subprocess.PIPE if capture_output else None)
    )
    stderr_dest = (
        sys.stderr if stream_output else (asyncio.subprocess.PIPE if capture_output else None)
    )

    process = await asyncio.create_subprocess_exec(
        *cmd_str,
        stdout=stdout_dest,
        stderr=stderr_dest,
        cwd=str(cwd_path),
        env=env or os.environ.copy(),
    )

    try:
        stdout_bytes, stderr_bytes = await process.communicate()
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            process.terminate()
            await process.wait()
        raise

    stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
    stderr = stderr_bytes.decode().strip() if stderr_bytes else ""

    result = CommandResult(
        returncode=process.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        cmd=cmd_str,
    )

    if check and result.returncode != 0:
        logger.error(f"Command failed: {result.cmd}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.error(f"STDERR: {result.stderr}")
        raise CommandError(result.returncode, result.stdout, result.stderr, result.cmd)

    return result


class DockerClient:
    """Generic wrapper for Docker CLI operations."""

    @staticmethod
    async def get_status(container: str) -> tuple[str, str]:
        """Returns (state, health) for a container."""
        try:
            result = await async_run_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                    container,
                ],
                check=False,
            )
            if result.returncode != 0:
                return "not_found", "none"
            parts = result.stdout.strip().split()
            if not parts:
                return "unknown", "none"
            return (parts[0], parts[1]) if len(parts) >= 2 else (parts[0], "none")
        except Exception:
            return "unknown", "none"


class HealthProbe:
    """Base class for health probes."""

    async def probe(self) -> HealthStatus:
        raise NotImplementedError


class DockerProbe(HealthProbe):
    """Probes container status and health label."""

    def __init__(self, container_name: str):
        self.container = container_name

    async def probe(self) -> HealthStatus:
        state, health = await DockerClient.get_status(self.container)

        if health == "healthy":
            return HealthStatus.HEALTHY
        if state in ["exited", "dead"]:
            return HealthStatus.CRASHED
        if state in ["restarting", "created"]:
            return HealthStatus.STARTING
        if state == "not_found":
            return HealthStatus.NOT_FOUND
        if state == "running" and health == "none":
            return HealthStatus.HEALTHY
        return HealthStatus.UNKNOWN


class HttpProbe(HealthProbe):
    """Probes an HTTP endpoint for readiness."""

    def __init__(
        self,
        url: str,
        timeout: float = 2.0,
        validator: AsyncValidator | None = None,
    ):
        self.url = url
        self.timeout = timeout
        self.validator = validator

    async def probe(self) -> HealthStatus:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.url, timeout=self.timeout)
                if response.status_code == 200:
                    if self.validator and not await self.validator(response):
                        return HealthStatus.STARTING
                    return HealthStatus.HEALTHY
                return HealthStatus.STARTING
            except (OSError, httpx.HTTPError):
                return HealthStatus.STARTING


# Crash detection patterns shared by LogProbe and ServiceHealthManager
CRASH_PATTERNS: list[str] = [
    r"Traceback \(most recent call last\):",
    r"FATAL:",
    r"ERROR:.*failed",
    r"RuntimeError:",
    r"NotImplementedError:",
    r"AssertionError:",
]


class LogProbe(HealthProbe):
    """Scans docker logs for crash patterns."""

    def __init__(
        self, container_name: str, tail: int = 50, extra_patterns: list[str] | None = None
    ):
        self.container = container_name
        self.tail = tail
        self.patterns = CRASH_PATTERNS + (extra_patterns or [])
        self._last_crash_pattern: str | None = None

    async def probe(self) -> HealthStatus:
        cmd = ["docker", "logs", "--tail", str(self.tail), self.container]
        try:
            result = await async_run_command(cmd, check=False)
            full_logs = f"{result.stdout}\n{result.stderr}"
            for pattern in self.patterns:
                if re.search(pattern, full_logs, re.IGNORECASE):
                    # Only log warning if it's a new pattern detection to reduce noise
                    if self._last_crash_pattern != pattern:
                        logger.warning(f"Detected crash pattern in {self.container}: {pattern}")
                        self._last_crash_pattern = pattern
                    return HealthStatus.CRASHED
            return HealthStatus.UNKNOWN
        except Exception:
            logger.exception(f"LogProbe encountered an error while scanning {self.container}")
            return HealthStatus.UNKNOWN


class ServiceHealthManager:
    """Orchestrates health probes for a service."""

    def __init__(self, container_name: str, probes: list[HealthProbe] | None = None):
        self.container = container_name
        self.probes = probes or [DockerProbe(container_name), LogProbe(container_name)]

    async def wait_for_ready(self, timeout: int = 60, stream_logs: bool = False) -> bool:
        """Wait until the service is healthy or definitely crashed."""

        async def poll_probes():
            while True:
                statuses = await asyncio.gather(*(p.probe() for p in self.probes))
                if HealthStatus.CRASHED in statuses:
                    logger.error(f"Service {self.container} has crashed (detected by probe).")
                    return False
                if HealthStatus.HEALTHY in statuses:
                    logger.info(f"Service {self.container} is READY.")
                    return True
                await asyncio.sleep(2)

        async def tail_for_crashes():

            if "sparkrun" in self.container:
                cmd = [
                    "docker",
                    "exec",
                    self.container,
                    "tail",
                    "-n",
                    "+0",
                    "-f",
                    "/tmp/sparkrun_serve.log",
                ]
            else:
                cmd = ["docker", "logs", "-f", self.container]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )

            try:
                assert process.stdout is not None  # guaranteed by PIPE above
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        break
                    line_str = line.decode(errors="replace").strip()
                    if line_str:
                        logger.debug(f"[{self.container}] {line_str}")
                        for pattern in CRASH_PATTERNS:
                            if re.search(pattern, line_str, re.IGNORECASE):
                                logger.error(
                                    f"❌ FATAL ERROR DETECTED IN {self.container}: {line_str}"
                                )
                                return False
                # If stream ends without crash, just wait forever so poll_probes determines outcome
                await asyncio.sleep(timeout)
                return False
            finally:
                with contextlib.suppress(Exception):
                    process.terminate()
                    await process.wait()

        tasks = [asyncio.create_task(poll_probes())]
        if stream_logs:
            tasks.append(asyncio.create_task(tail_for_crashes()))

        done, pending = await asyncio.wait(
            tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )

        for p in pending:
            p.cancel()

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        if not done:
            logger.error(f"Timeout of {timeout}s reached waiting for {self.container}.")
            return False

        # Return the result of the first task to finish (either health pass, or crash fail)
        try:
            return done.pop().result()
        except Exception as e:
            logger.error(f"Health check for {self.container} crashed unexpectedly: {e}")
            return False
