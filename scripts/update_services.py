#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
from pathlib import Path

"""
update_services.py - Modern, async-first service orchestration.
"""

import asyncio
import signal
import sys
import termios
import tty
from abc import ABC, abstractmethod
from contextvars import ContextVar
from datetime import datetime
import psutil

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from rich.console import Console
from rich.table import Table

# Inject root dir for core imports

from core.constants import PROJECT_ROOT
from core.schemas import ServiceStatus
from core.utils import (
    CommandError,
    DockerProbe,
    HttpProbe,
    LogProbe,
    ServiceHealthManager,
    async_run_command,
)
from scripts.update_openclaw import OpenClawUpdater
from scripts.update_sparkrun import SparkrunUpdater

current_service: ContextVar[str] = ContextVar("current_service", default="")

import contextlib
import os

STATSD_HOST = os.environ.get("SPARKRUN_STATSD_HOST", "127.0.0.1")
STATSD_PORT = int(os.environ.get("SPARKRUN_STATSD_PORT", "8125"))
STATSD_ADDR = (STATSD_HOST, STATSD_PORT)

class StatsdClient:
    def __init__(self) -> None:
        self.writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()

    async def send(self, msg: str) -> None:
        async with self.lock:
            if self.writer is None or self.writer.is_closing():
                try:
                    _, self.writer = await asyncio.wait_for(
                        asyncio.open_connection(*STATSD_ADDR), timeout=1.0
                    )
                except Exception as e:
                    logger.debug(f"Failed to connect to StatsD: {e}")
                    self.writer = None
                    return
            try:
                self.writer.write(msg.encode("utf-8"))
                await self.writer.drain()
            except Exception as e:
                logger.debug(f"StatsD write exception: {e}")
                if self.writer:
                    with contextlib.suppress(Exception):
                        self.writer.close()
                    self.writer = None

statsd = StatsdClient()


class Settings(BaseSettings):
    """Global configuration for service updates."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Field(default_factory=lambda: PROJECT_ROOT)
    vllm_spark_api_key: str | None = Field(default=None, alias="VLLM_SPARK_API_KEY")
    pull_latest: bool = False


async def pre_flight_checks(settings: Settings):
    console = Console()
    console.print("\n[bold cyan]Checking system readiness...[/]")

    # Check .env
    env_path = settings.project_root / ".env"
    if not env_path.exists():
        console.print(f"[red]❌ Error:[/] Missing .env file at {env_path}")
        sys.exit(1)

    # Check Docker daemon
    try:
        await async_run_command(["docker", "info"], check=True, capture_output=True)
    except Exception:
        console.print("[red]❌ Error:[/] Docker daemon is not running or accessible.")
        sys.exit(1)

    console.print("[green]✔ Pre-flight complete.[/]\n")


async def cleanup_zombies(settings: Settings):
    """The 'Zombie Protocol' - cleans up stuck tasks and stale containers."""
    console = Console()
    console.print("[bold yellow]🧟 Executing Zombie Protocol...[/]")

    # 1. Clear stuck OpenClaw tasks
    from core.constants import OPENCLAW_HOME
    task_db = OPENCLAW_HOME / "tasks" / "runs.sqlite"
    if task_db.exists():
        console.print(f"  → Clearing zombie tasks in {task_db}")
        try:
            await async_run_command(
                [
                    "sqlite3",
                    str(task_db),
                    "UPDATE task_runs SET status = 'failed', error = 'Zombie task cleared by update_services' WHERE status = 'running';",
                ],
                check=False,
            )
        except Exception as e:
            logger.warning(f"Failed to clear zombie tasks: {e}")

    # 2. Cleanup stale containers (orphaned or exited long ago)
    console.print("  → Cleaning up stale containers and networks...")
    try:
        # Remove exited containers
        await async_run_command(["docker", "container", "prune", "-f"], check=False)
        # Remove unused networks
        await async_run_command(["docker", "network", "prune", "-f"], check=False)
    except Exception as e:
        logger.warning(f"Docker cleanup failed: {e}")


class ServiceState:
    """Tracks the live state of a service for the dashboard."""

    def __init__(self, name: str):
        self.name = name
        self.status = ServiceStatus.WAITING
        self.task = "Idle"
        self.progress = 0.0
        self.error = None
        self.note = ""
        self.start_time = None
        self.end_time = None
        self.done_event = asyncio.Event()

    def set_task(self, task: str, progress: float = 0.0):
        self.task = task
        self.progress = progress
        self.status = ServiceStatus.RUNNING
        self.note = task
        if not self.start_time:
            self.start_time = datetime.now()
        asyncio.create_task(statsd.send(f"update_services_progress:{progress}|g|#service:{self.name}\n"))
        asyncio.create_task(statsd.send(f"update_services_status:1|g|#service:{self.name}\n"))

    def complete(self):
        self.status = ServiceStatus.COMPLETE
        self.progress = 100.0
        self.end_time = datetime.now()
        self.note = "Complete."
        logger.success(f"[{self.name}] Service update COMPLETE.")
        self.done_event.set()
        asyncio.create_task(statsd.send(f"update_services_progress:100.0|g|#service:{self.name}\n"))
        asyncio.create_task(statsd.send(f"update_services_status:2|g|#service:{self.name}\n"))

    def fail(self, error: str):
        self.status = ServiceStatus.FAILED
        self.error = error
        self.note = str(error)
        self.end_time = datetime.now()
        logger.error(f"[{self.name}] Service update FAILED: {error}")
        self.done_event.set()
        asyncio.create_task(statsd.send(f"update_services_status:3|g|#service:{self.name}\n"))


class Service(ABC):
    """Abstract base class for all manageable services."""

    dependencies: list[str] = []

    def __init__(self, name: str, state: ServiceState, settings: Settings):
        self.name = name
        self.state = state
        self.settings = settings

    @abstractmethod
    async def update(self) -> None:
        """Run the full update lifecycle for this service."""

    async def run_compose(self, directory: Path, *args: str, check: bool = True):
        """Execute docker compose in a specific directory with shared env files."""
        cmd = ["docker", "compose"]
        root_env = self.settings.project_root / ".env"
        if root_env.exists():
            cmd.extend(["--env-file", str(root_env)])

        local_env = directory / ".env"
        if local_env.exists():
            cmd.extend(["--env-file", str(local_env)])

        cmd.extend(args)
        try:
            result = await async_run_command(cmd, cwd=directory, check=check)
            with open("deployment.log", "a") as f:
                f.write(f"\n--- [SUCCESS] {' '.join(cmd)} in {directory} ---\n")
                if result.stdout:
                    f.write(result.stdout + "\n")
                if result.stderr:
                    f.write(result.stderr + "\n")
            return result
        except CommandError as e:
            with open("deployment.log", "a") as f:
                f.write(f"\n--- [FAILED] {' '.join(cmd)} in {directory} ---\n")
                if e.stdout:
                    f.write(e.stdout + "\n")
                if e.stderr:
                    f.write(e.stderr + "\n")
            self.state.fail(f"Compose failed: {e.stderr[:100]}")
            raise


class SparkrunService(Service):
    async def update(self) -> None:
        self.state.set_task("Initializing", 10)
        updater = SparkrunUpdater(
            pull_latest=self.settings.pull_latest, project_root=self.settings.project_root
        )

        self.state.set_task("Updating source & Rebase", 40)
        await updater.update_source()

        self.state.set_task("Installing", 80)
        await updater.run_install()
        self.state.complete()


class CloudflareService(Service):
    async def update(self) -> None:
        cf_dir = self.settings.project_root / "cloudflare"
        tunnel_sh = cf_dir / "tunnel.sh"

        if self.settings.pull_latest:
            self.state.set_task("Pulling images", 20)
            await async_run_command(
                [str(tunnel_sh), "pull", "--ignore-pull-failures"], cwd=cf_dir, check=False
            )

        self.state.set_task("Deploying tunnel", 60)
        await async_run_command([str(tunnel_sh), "up", "-d"], cwd=cf_dir)

        self.state.set_task("Probing health", 80)
        manager = ServiceHealthManager("cloudflared")
        if await manager.wait_for_ready(timeout=60):
            self.state.complete()
        else:
            self.state.fail("Health check timed out or failed")


class VllmService(Service):
    dependencies = ["SparkRun"]

    async def update(self) -> None:
        vllm_current = self.settings.project_root / "current"
        if not vllm_current.exists():
            self.state.fail("No active stack found in 'current/'")
            return

        if self.settings.pull_latest:
            self.state.set_task("Pulling vLLM", 20)
            await self.run_compose(vllm_current, "pull", "--ignore-pull-failures", check=False)

        self.state.set_task("Restarting stack", 50)
        # Force kill orphaned vLLM/EngineCore processes (The "Zombie Protocol")
        logger.info("Purging orphaned VLLM/EngineCore processes...")
        await async_run_command(["pkill", "-9", "-f", "VLLM|sparkrun|vllm"], check=False)

        launch_script = vllm_current / "launch.sh"
        if launch_script.exists():
            await async_run_command([str(launch_script)], cwd=vllm_current)
        else:
            await self.run_compose(vllm_current, "up", "-d", "--remove-orphans")

        self.state.set_task("Probing health", 80)
        # Use centralized health manager with explicit probes
        manager = ServiceHealthManager(
            "vllm-gateway",
            probes=[
                DockerProbe("vllm-gateway"),
                LogProbe("vllm-gateway"),
                HttpProbe("http://localhost:4000/v1/models"),
            ],
        )
        if await manager.wait_for_ready(timeout=60):
            self.state.complete()
        else:
            self.state.fail("Health check timed out")


class MonitoringService(Service):
    async def update(self) -> None:
        mon_dir = self.settings.project_root / "monitoring"

        if self.settings.pull_latest:
            self.state.set_task("Pulling images", 20)
            await self.run_compose(mon_dir, "pull", "--ignore-pull-failures", check=False)

        self.state.set_task("Deploying stack", 60)
        await self.run_compose(mon_dir, "up", "-d", "--build")
        self.state.complete()


class RegistrySyncService(Service):
    dependencies = ["vLLM"]

    async def update(self) -> None:
        self.state.set_task("Syncing models to gateway", 50)
        from scripts.sync_registry import sync_registry

        await sync_registry(project_root=self.settings.project_root)
        self.state.complete()


class OpenClawService(Service):
    dependencies = ["RegistrySync"]

    async def update(self) -> None:
        self.state.set_task("Initializing", 10)

        updater = OpenClawUpdater(
            pull_latest=self.settings.pull_latest, project_root=self.settings.project_root
        )

        self.state.set_task("Updating source", 30)
        await updater.update_source()

        self.state.set_task("Building sandbox image", 45)
        await updater.build_sandbox_image()

        self.state.set_task("Deploying", 80)
        await updater.run_compose_up()
        self.state.complete()


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.console = Console()
        self.states = {
            "SparkRun": ServiceState("SparkRun"),
            "Cloudflare": ServiceState("Cloudflare"),
            "vLLM": ServiceState("vLLM"),
            "RegistrySync": ServiceState("RegistrySync"),
            "Monitoring": ServiceState("Monitoring"),
            "OpenClaw": ServiceState("OpenClaw"),
        }
        self.services = [
            SparkrunService("SparkRun", self.states["SparkRun"], settings),
            CloudflareService("Cloudflare", self.states["Cloudflare"], settings),
            VllmService("vLLM", self.states["vLLM"], settings),
            RegistrySyncService("RegistrySync", self.states["RegistrySync"], settings),
            MonitoringService("Monitoring", self.states["Monitoring"], settings),
            OpenClawService("OpenClaw", self.states["OpenClaw"], settings),
        ]

    def render_table(self) -> Table:
        ram_pct = psutil.virtual_memory().percent
        cpu_pct = psutil.cpu_percent()

        table = Table(
            title="[bold blue]Service Update Dashboard[/]",
            title_justify="left",
            expand=True,
            caption=f"[dim]Sys Res: RAM {ram_pct}% | CPU {cpu_pct}%[/dim]",
            caption_justify="right",
        )
        table.add_column("Service", style="cyan", no_wrap=True)
        table.add_column("Task", style="magenta")
        table.add_column("Status", justify="center")
        table.add_column("Progress")
        table.add_column("Notes", style="dim", ratio=1, no_wrap=True, overflow="ellipsis")

        for name, state in self.states.items():
            status_color = {
                ServiceStatus.WAITING: "white",
                ServiceStatus.RUNNING: "yellow",
                ServiceStatus.COMPLETE: "green",
                ServiceStatus.FAILED: "red",
            }.get(state.status, "white")

            status_text = state.status.value.capitalize()
            progress_bar = f"[{'#' * int(state.progress // 10):<10}] {state.progress:.0f}%"

            note_str = state.error or state.note

            table.add_row(
                name,
                state.task,
                f"[{status_color}]{status_text}[/]",
                progress_bar,
                note_str,
            )
        return table

    async def run_service(self, service: Service, semaphore: asyncio.Semaphore):
        """Wait for dependencies then run the service update."""
        current_service.set(service.name)
        try:
            for dep_name in service.dependencies:
                dep_state = self.states.get(dep_name)
                if not dep_state:
                    raise ValueError(
                        f"Service {service.name} depends on unknown service {dep_name}"
                    )

                # Wait for the dependency to finish (Complete or Failed)
                await dep_state.done_event.wait()

                if dep_state.status == ServiceStatus.FAILED:
                    service.state.fail(f"Aborted: dependency '{dep_name}' failed")
                    return

            async with semaphore:
                await service.update()
        except asyncio.CancelledError:
            service.state.fail("Cancelled")
            raise
        except Exception as e:
            logger.exception(f"Service {service.name} failed")
            service.state.fail(str(e))
        finally:
            # Ensure event is ALWAYS set to prevent downstream deadlocks
            if not service.state.done_event.is_set():
                service.state.fail("Unknown internal error")

    async def run(self):
        self.console.print(
            f"🚀 [bold]Starting Orchestrated Update[/] (Pull: {'ON' if self.settings.pull_latest else 'OFF'})"
        )

        semaphore = asyncio.Semaphore(2)  # Limit concurrent Docker/heavy I/O operations
        tasks = [asyncio.create_task(self.run_service(s, semaphore)) for s in self.services]

        # Use rich.live to constantly refresh the dashboard
        from rich.live import Live
        import contextlib

        @contextlib.contextmanager
        def prevent_tty_echo():
            if not sys.stdin.isatty():
                yield
                return
            fd = sys.stdin.fileno()
            old = None
            try:
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                yield
            except Exception:
                yield
            finally:
                if old is not None:
                    try:
                        termios.tcflush(fd, termios.TCIFLUSH)
                        termios.tcsetattr(fd, termios.TCSANOW, old)
                    except Exception:
                        pass

        with (
            prevent_tty_echo(),
            Live(
                self.render_table(), console=self.console, refresh_per_second=4, screen=True
            ) as live,
        ):
            # We concurrently check on the tasks and update the live table manually or via loop
            # Simple polling loop to update the table until all tasks are done
            while not all(t.done() for t in tasks):
                live.update(self.render_table())
                await asyncio.sleep(0.2)

            # One final update
            live.update(self.render_table())

        # Print final completed table so it permanently persists in terminal history
        self.console.print(self.render_table())

        # Finalize and wait to securely raise exceptions
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            self.console.print("[yellow]Update gracefully cancelled.[/]")
            raise
        except Exception:
            self.console.print("[red]Some services encountered errors.[/]")

        self.console.print(
            "\n[bold green]✨ All services processed.[/] (Check the table above for final status)"
        )


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Professional service updater.")
    parser.add_argument("--pull-latest", action="store_true", help="Pull latest images.")
    args = parser.parse_args()

    settings = Settings(pull_latest=args.pull_latest)

    # Wipe deployment.log
    with open("deployment.log", "w") as f:
        f.write("--- Deployment Log Initialization ---\n")

    await pre_flight_checks(settings)
    await cleanup_zombies(settings)

    # Configure loguru to be less noisy
    logger.remove()
    logger.add("update_services.log", level="DEBUG")

    orchestrator = Orchestrator(settings)

    def ui_sink(msg):
        svc_name = current_service.get()
        if svc_name and hasattr(orchestrator, "states") and svc_name in orchestrator.states:
            text = msg.record["message"].split("\n")[0]
            orchestrator.states[svc_name].note = text

    logger.add(ui_sink, level="INFO")

    await orchestrator.run()

    from scripts.wait_for_backends import wait_for_backends_to_load

    stack_dir = settings.project_root / "current"
    if stack_dir.exists():
        # Restore visible logging for the waiting phase
        logger.remove()
        logger.add(sys.stderr, level="INFO")

        console = Console()
        console.print("\n🔍 [bold]Waiting for updated backends to initialize and load models...[/]")
        await wait_for_backends_to_load(stack_dir)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Setup graceful signal handlers
    main_task = loop.create_task(main())

    for sig in (signal.SIGINT, signal.SIGTERM):
        import contextlib

        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, main_task.cancel)

    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        print("\nAborted by user.")
        sys.exit(1)
    except SystemExit as e:
        sys.exit(e.code)
    except Exception:
        logger.exception("Global failure")
        sys.exit(1)
    finally:
        loop.close()
