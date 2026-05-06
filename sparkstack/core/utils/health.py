import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from enum import Enum

import httpx
from loguru import logger

from sparkstack.core.utils.docker import DockerClient
from sparkstack.core.utils.shell import async_run_command

# Type alias for HTTP health check validators
AsyncValidator = Callable[[httpx.Response], Awaitable[bool]]


class HealthStatus(Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    CRASHED = "crashed"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"


class HealthProbe:
    """Base class for health probes."""

    async def probe(self) -> HealthStatus:
        raise NotImplementedError

    async def stream_crashes(self) -> AsyncIterator[str]:
        """Yields crash strings as they happen."""
        while True:
            await asyncio.sleep(86400)
            yield ""


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
    r"ERROR:.{0,100}failed",
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
                    if self._last_crash_pattern != pattern:
                        logger.warning(f"Detected crash pattern in {self.container}: {pattern}")
                        self._last_crash_pattern = pattern
                    return HealthStatus.CRASHED
            return HealthStatus.UNKNOWN
        except Exception:
            logger.exception(f"LogProbe encountered an error while scanning {self.container}")
            return HealthStatus.UNKNOWN

    def get_stream_cmd(self) -> list[str]:
        return ["docker", "logs", "-f", self.container]

    async def stream_crashes(self) -> AsyncIterator[str]:
        cmd = self.get_stream_cmd()
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                line_str = line.decode(errors="replace").strip()
                if line_str:
                    logger.debug(f"[{self.container}] {line_str}")
                    for pattern in self.patterns:
                        if re.search(pattern, line_str, re.IGNORECASE):
                            yield f"❌ FATAL ERROR DETECTED IN {self.container}: {line_str}"
            while True:
                await asyncio.sleep(86400)
                yield ""
        finally:
            with contextlib.suppress(Exception):
                process.terminate()
                await process.wait()


class SparkrunLogProbe(LogProbe):
    """Specific log probe that checks the internal serve log file instead of docker logs."""

    def get_stream_cmd(self) -> list[str]:
        return [
            "docker",
            "exec",
            self.container,
            "tail",
            "-n",
            "+0",
            "-f",
            "/tmp/sparkrun_serve.log",
        ]


class ServiceHealthManager:
    """Orchestrates health probes for a service."""

    def __init__(self, container_name: str, probes: list[HealthProbe] | None = None):
        self.container = container_name
        if probes is None:
            self.probes = [
                DockerProbe(container_name),
                SparkrunLogProbe(container_name)
                if "sparkrun" in container_name
                else LogProbe(container_name),
            ]
        else:
            self.probes = probes

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
            async def consume_crashes(probe: HealthProbe):
                async for crash_msg in probe.stream_crashes():
                    if crash_msg:
                        logger.error(crash_msg)
                        return False
                return True

            tasks = [asyncio.create_task(consume_crashes(p)) for p in self.probes]
            if not tasks:
                await asyncio.sleep(timeout)
                return False

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            return done.pop().result()

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

        try:
            return done.pop().result()
        except Exception as e:
            logger.error(f"Health check for {self.container} crashed unexpectedly: {e}")
            return False
