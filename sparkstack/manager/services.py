import asyncio
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from loguru import logger

from sparkstack.core.builders.monitoring import MonitoringBuilder
from sparkstack.core.builders.stack import StackBuilder
from sparkstack.core.ipc_server import StateUpdateEvent
from sparkstack.core.progress import StackProgress
from sparkstack.core.schemas import ServiceStatus
from sparkstack.core.statsd import StatsdClient
from sparkstack.core.utils.health import (
    DockerProbe,
    HttpProbe,
    LogProbe,
    ServiceHealthManager,
)
from sparkstack.core.utils.shell import CommandError, async_run_compose
from sparkstack.manager.launch import launch_stack
from sparkstack.manager.sync_registry import sync_registry
from sparkstack.manager.update_openclaw import OpenClawUpdater
from sparkstack.manager.update_sparkrun import SparkrunUpdater


class ServiceState:
    """Tracks the live state of a service for the dashboard."""

    def __init__(self, name: str, ipc=None, statsd: StatsdClient | None = None):
        self.name = name
        self.status = ServiceStatus.WAITING
        self.task = "Idle"
        self.progress = 0.0
        self.error = None
        self.note = ""
        self.start_time = None
        self.done_event = asyncio.Event()
        self._ipc = ipc  # Optional IPCServer for broadcasting
        self._statsd = statsd

    def _broadcast(self):
        """Push current state to IPC clients if server is attached."""
        if self._ipc is not None:
            self._ipc.update_state(
                StateUpdateEvent(
                    service=self.name,
                    status=self.status.value,
                    progress=self.progress,
                    note=self.error or self.note,
                )
            )

    def set_task(self, task: str, progress: float = 0.0):
        self.task = task
        self.progress = progress
        self.status = ServiceStatus.RUNNING
        self.note = task
        if not self.start_time:
            self.start_time = datetime.now()
        self._broadcast()
        if self._statsd:
            asyncio.create_task(
                self._statsd.send(
                    f"vllm_sparkrun_deploy_step_progress:{progress}|g|#service:{self.name}\n"
                )
            )
            asyncio.create_task(
                self._statsd.send(f"vllm_sparkrun_deploy_step_status:1|g|#service:{self.name}\n")
            )

    def complete(self):
        self.status = ServiceStatus.COMPLETE
        self.progress = 100.0
        self.note = "Complete."
        logger.success(f"[{self.name}] Service update COMPLETE.")
        self.done_event.set()
        self._broadcast()
        if self._statsd:
            asyncio.create_task(
                self._statsd.send(
                    f"vllm_sparkrun_deploy_step_progress:100.0|g|#service:{self.name}\n"
                )
            )
            asyncio.create_task(
                self._statsd.send(f"vllm_sparkrun_deploy_step_status:2|g|#service:{self.name}\n")
            )

    def fail(self, error: str):
        self.status = ServiceStatus.FAILED
        self.error = error
        self.note = str(error)
        logger.error(f"[{self.name}] Service update FAILED: {error}")
        self.done_event.set()
        self._broadcast()
        if self._statsd:
            asyncio.create_task(
                self._statsd.send(f"vllm_sparkrun_deploy_step_status:3|g|#service:{self.name}\n")
            )


class Service(ABC):
    """Abstract base class for all manageable services."""

    dependencies: list[str] = []

    def __init__(self, name: str, state: ServiceState, settings):
        self.name = name
        self.state = state
        self.settings = settings
        self.progress = StackProgress()

    @abstractmethod
    async def update(self) -> None:
        """Run the full update lifecycle for this service."""

    async def run_compose(
        self, directory: Path, *args: str, check: bool = True, project_name: str | None = None
    ):
        """Execute docker compose in a specific directory with shared env files."""
        try:
            result = await async_run_compose(
                directory,
                *args,
                project_root=self.settings.project_root,
                project_name=project_name,
                check=check,
                capture_output=True,
            )
            logger.debug(f"[SUCCESS] docker compose {' '.join(args)} in {directory}")
            if result.stdout:
                logger.debug(result.stdout)
            if result.stderr:
                logger.debug(result.stderr)
            return result
        except CommandError as e:
            logger.error(f"[FAILED] docker compose {' '.join(args)} in {directory}")
            if e.stdout:
                logger.error(e.stdout)
            if e.stderr:
                logger.error(e.stderr)
            self.state.fail(f"Compose failed: {e.stderr[:100]}")
            raise


class SparkrunService(Service):
    async def update(self) -> None:
        updater = SparkrunUpdater(
            pull_latest=self.settings.pull_latest, project_root=self.settings.project_root
        )

        async for task_name, progress in updater.run_events():
            self.state.set_task(task_name, progress)
        self.state.complete()


class CloudflareService(Service):
    dependencies = []

    async def update(self) -> None:
        cf_dir = self.settings.project_root / "services" / "cloudflare"
        self.progress.begin_phases(3 if self.settings.pull_latest else 2)
        phase_num = 1

        if self.settings.pull_latest:
            self.progress.phase(phase_num, "Pulling images")
            self.state.set_task("Pulling images", 20)
            await self.run_compose(cf_dir, "pull", "--ignore-pull-failures", check=False)
            self.progress.phase_end()
            phase_num += 1

        self.progress.phase(phase_num, "Deploying tunnel")
        self.state.set_task("Deploying tunnel", 60)
        await self.run_compose(cf_dir, "up", "-d", "--force-recreate")
        self.progress.phase_end()
        phase_num += 1

        self.progress.phase(phase_num, "Probing health")
        self.state.set_task("Probing health", 80)
        manager = ServiceHealthManager("cloudflared")
        if await manager.wait_for_ready(timeout=60):
            self.progress.phase_end()
            self.state.complete()
        else:
            self.state.fail("Health check timed out or failed")


class VllmService(Service):
    dependencies = ["SparkRun", "Monitoring", "OpenClaw"]

    async def update(self) -> None:
        vllm_current = (self.settings.project_root / "current").resolve()
        if not vllm_current.exists():
            self.state.fail("No active stack found in 'current/'")
            return

        self.progress.begin_phases(4 if self.settings.pull_latest else 3)
        phase_num = 1

        if self.settings.pull_latest:
            self.progress.phase(phase_num, "Pulling vLLM")
            self.state.set_task("Pulling vLLM", 20)
            await self.run_compose(
                vllm_current, "pull", "--ignore-pull-failures", check=False, project_name="current"
            )
            self.progress.phase_end()
            phase_num += 1

        # Always rebuild configs from stack.yaml to pick up builder changes.
        self.progress.phase(phase_num, "Rebuilding configs")
        self.state.set_task("Rebuilding configs", 40)
        stack_yaml = vllm_current / "stack.yaml"
        if stack_yaml.exists():
            await StackBuilder.rebuild_from_stack(vllm_current)
        self.progress.phase_end()
        phase_num += 1

        self.progress.phase(phase_num, "Restarting stack")
        self.state.set_task("Restarting stack", 60)

        if stack_yaml.exists():
            await launch_stack(vllm_current, rebuild_images=self.settings.pull_latest)
        else:
            compose_yaml = vllm_current / "docker-compose.yaml"
            if compose_yaml.exists():
                await self.run_compose(
                    vllm_current, "up", "-d", "--remove-orphans", project_name="current"
                )
        self.progress.phase_end()
        phase_num += 1

        self.progress.phase(phase_num, "Probing health")
        self.state.set_task("Probing health", 80)
        # Use centralized health manager with explicit probes
        manager = ServiceHealthManager(
            "litellm",
            probes=[
                DockerProbe("litellm"),
                LogProbe("litellm"),
                HttpProbe("http://localhost:4000/health"),
            ],
        )
        if await manager.wait_for_ready(timeout=60):
            self.progress.phase_end()
            self.state.complete()
        else:
            self.state.fail("Health check timed out")


class MonitoringService(Service):
    async def update(self) -> None:
        mon_dir = self.settings.project_root / "services" / "monitoring"
        stack_dir = self.settings.project_root / "current"

        # Ensure config files exist before starting to avoid docker directory creation
        stack_dir.mkdir(parents=True, exist_ok=True)
        MonitoringBuilder(stack_dir).write()

        # Inject SPARKSTACK_STACK_DIR for compose
        os.environ["SPARKSTACK_STACK_DIR"] = str(stack_dir.resolve())

        self.progress.begin_phases(3 if self.settings.pull_latest else 2)
        phase_num = 1

        if self.settings.pull_latest:
            self.progress.phase(phase_num, "Pulling images")
            self.state.set_task("Pulling images", 20)
            await self.run_compose(mon_dir, "pull", "--ignore-pull-failures", check=False)
            self.progress.phase_end()
            phase_num += 1

        self.progress.phase(phase_num, "Deploying stack")
        self.state.set_task("Deploying stack", 60)
        await self.run_compose(mon_dir, "up", "-d", "--build")
        self.progress.phase_end()
        phase_num += 1

        self.progress.phase(phase_num, "Probing health")
        self.state.set_task("Probing health", 80)
        manager = ServiceHealthManager(
            "vllm-progress-manager", probes=[HttpProbe("http://localhost:8126/status", timeout=2.0)]
        )
        if await manager.wait_for_ready(timeout=60):
            self.progress.phase_end()
            self.state.complete()
        else:
            self.state.fail("Monitoring telemetry health check timed out")


class RegistrySyncService(Service):
    dependencies = ["vLLM"]

    async def update(self) -> None:
        self.state.set_task("Syncing models to gateway", 50)

        await sync_registry(project_root=self.settings.project_root)
        self.state.complete()


class OpenClawService(Service):
    dependencies = []

    async def update(self) -> None:
        updater = OpenClawUpdater(
            pull_latest=self.settings.pull_latest, project_root=self.settings.project_root
        )

        async for task_name, progress in updater.run_events():
            self.state.set_task(task_name, progress)
        self.state.complete()
