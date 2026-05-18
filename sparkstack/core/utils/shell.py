import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


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

    logger.debug(f"Running command: {' '.join(cmd)} (cwd: {cwd_path})")

    # If stream_output is True, pipe stdout and stderr to the process's standard streams instead of capturing
    stdout_dest = (
        sys.stdout if stream_output else (asyncio.subprocess.PIPE if capture_output else None)
    )
    stderr_dest = (
        sys.stderr if stream_output else (asyncio.subprocess.PIPE if capture_output else None)
    )

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=stdout_dest,
        stderr=stderr_dest,
        cwd=str(cwd_path),
        env=env or os.environ.copy(),
    )

    try:
        stdout_bytes, stderr_bytes = await process.communicate()
    except asyncio.CancelledError:
        try:
            process.terminate()
            await process.wait()
        except Exception:
            pass
        raise

    stdout = stdout_bytes.decode().strip() if stdout_bytes else ""
    stderr = stderr_bytes.decode().strip() if stderr_bytes else ""

    result = CommandResult(
        returncode=process.returncode or 0,
        stdout=stdout,
        stderr=stderr,
        cmd=cmd,
    )

    if check and result.returncode != 0:
        logger.error(f"Command failed: {result.cmd}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.error(f"STDERR: {result.stderr}")
        raise CommandError(result.returncode, result.stdout, result.stderr, result.cmd)

    return result


async def async_run_compose(
    directory: Path | str,
    *args: str,
    project_root: Path | str | None = None,
    project_name: str | None = None,
    check: bool = True,
    capture_output: bool = True,
    stream_output: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Execute docker compose in a specific directory with shared env files automatically included."""
    directory = Path(directory)
    cmd = ["docker", "compose"]

    if project_name:
        cmd.extend(["--project-name", project_name])

    if project_root:
        root_env = Path(project_root) / ".env"
        if root_env.exists():
            cmd.extend(["--env-file", str(root_env)])

    local_env = directory / ".env"
    if local_env.exists():
        cmd.extend(["--env-file", str(local_env)])

    cmd.extend(args)

    return await async_run_command(
        cmd,
        cwd=directory,
        env=env,
        check=check,
        capture_output=capture_output,
        stream_output=stream_output,
    )
