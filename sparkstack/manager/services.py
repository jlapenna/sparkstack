import asyncio
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from sparkstack.core.builders.monitoring import MonitoringBuilder
from sparkstack.core.builders.stack import StackBuilder
from sparkstack.core.env import SPARK_NODE_TARGET, WORKER_TAILNET_IP
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
        logger.success("Service update COMPLETE.")
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
        self.note = error
        logger.error(f"Service update FAILED: {error}")
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
        self,
        directory: Path,
        *args: str,
        check: bool = True,
        project_name: str | None = None,
        env: dict[str, str] | None = None,
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
                env=env,
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

    async def _pull_images(
        self,
        directory: Path,
        phase_num: int,
        task_name: str = "Pulling images",
        project_name: str | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        """Helper to pull docker images if settings.pull_latest is True."""
        if self.settings.pull_latest:
            self.progress.phase(phase_num, task_name)
            self.state.set_task(task_name, 20)
            await self.run_compose(
                directory,
                "pull",
                "--ignore-pull-failures",
                check=False,
                project_name=project_name,
                env=env,
            )
            self.progress.phase_end()
            return phase_num + 1
        return phase_num

    async def _deploy_compose(
        self,
        directory: Path,
        phase_num: int,
        up_args: list[str],
        down_args: list[str] | None = None,
        compose_args: list[str] | None = None,
        task_name: str = "Deploying stack",
        project_name: str | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        """Helper to execute down (optional) then up for docker compose.

        Args:
            compose_args: Top-level compose flags (e.g. ``-f file.yml``) placed
                          *before* the ``up``/``down`` subcommand.
            up_args: Flags placed *after* the ``up`` subcommand.
            down_args: Flags placed *after* the ``down`` subcommand.
        """
        prefix = compose_args or []
        self.progress.phase(phase_num, task_name)
        self.state.set_task(task_name, 60)
        if down_args:
            await self.run_compose(
                directory,
                *prefix,
                "down",
                *down_args,
                check=False,
                project_name=project_name,
                env=env,
            )
        await self.run_compose(
            directory, *prefix, "up", *up_args, project_name=project_name, env=env
        )
        self.progress.phase_end()
        return phase_num + 1

    async def _probe_health(
        self,
        phase_num: int,
        manager: ServiceHealthManager,
        timeout: int = 60,
        task_name: str = "Probing health",
        fail_msg: str | None = None,
    ) -> None:
        """Helper to probe service health and complete the service update."""
        self.progress.phase(phase_num, task_name)
        self.state.set_task(task_name, 80)
        if await manager.wait_for_ready(timeout=timeout):
            self.progress.phase_end()
            self.state.complete()
        else:
            self.state.fail(fail_msg or f"{task_name} timed out or failed")


class UpdaterService(Service):
    """A generic Service that delegates its update to a BaseUpdater."""

    updater_class: type[Any] | None = None

    async def update(self) -> None:
        if self.updater_class is None:
            raise NotImplementedError("updater_class must be defined on subclass")

        updater = self.updater_class(
            pull_latest=self.settings.pull_latest, project_root=self.settings.project_root
        )

        async for task_name, progress in updater.run_events():
            self.state.set_task(task_name, progress)
        self.state.complete()


class SparkrunService(UpdaterService):
    updater_class = SparkrunUpdater


class CloudflareService(Service):
    dependencies = []

    async def update(self) -> None:
        cf_dir = self.settings.project_root / "services" / "cloudflare"
        self.progress.begin_phases(3 if self.settings.pull_latest else 2)
        phase_num = 1

        phase_num = await self._pull_images(cf_dir, phase_num)

        # down first to clear stale container references that cause
        # "No such container" errors on force-recreate
        phase_num = await self._deploy_compose(
            cf_dir,
            phase_num,
            down_args=["--remove-orphans"],
            up_args=["-d", "--force-recreate"],
            task_name="Deploying tunnel",
        )

        await self._probe_health(
            phase_num,
            ServiceHealthManager("cloudflared"),
            fail_msg="Health check timed out or failed",
        )


class HeadscaleService(Service):
    """Deploys the Headscale control plane for the Tailscale overlay network.

    This service is only activated when the overlay network is configured
    (SPARKSTACK_HEADSCALE_SERVER and SPARKSTACK_HEADSCALE_AUTH_KEY are set).
    It is a foundational service with no dependencies — Tailscale sidecars
    cannot authenticate until Headscale is healthy.
    """

    dependencies = []

    async def update(self) -> None:
        from sparkstack.core.env import is_overlay_configured  # noqa: PLC0415

        if not is_overlay_configured():
            self.state.status = ServiceStatus.SKIPPED
            self.state.note = "Overlay not configured (missing SPARKSTACK_HEADSCALE_* env vars)"
            self.state.done_event.set()
            self.state._broadcast()
            return

        hs_dir = self.settings.project_root / "services" / "headscale"
        self.progress.begin_phases(3 if self.settings.pull_latest else 2)
        phase_num = 1

        phase_num = await self._pull_images(hs_dir, phase_num)

        phase_num = await self._deploy_compose(
            hs_dir,
            phase_num,
            up_args=["-d", "--force-recreate"],
            task_name="Deploying Headscale control plane",
        )

        manager = ServiceHealthManager(
            "sparkstack-headscale",
            probes=[DockerProbe("sparkstack-headscale")],
        )
        await self._probe_health(
            phase_num,
            manager,
            timeout=30,
            fail_msg="Headscale health check timed out",
        )

        self.state.note = "Deploying head sidecar"
        self.state._broadcast()

        try:
            from sparkstack.core.env import (  # noqa: PLC0415
                SPARKSTACK_HEAD_TAILNET_IP,
                SPARKSTACK_HEADSCALE_AUTH_KEY,
                set_env,
            )
            from sparkstack.manager.remote import (  # noqa: PLC0415
                deploy_head_sidecar,
                deploy_worker_sidecar,
                get_headscale_auth_key,
                poll_sidecar_health,
                resolve_tailnet_ip,
            )

            # --- Head sidecar ---
            auth_key = SPARKSTACK_HEADSCALE_AUTH_KEY
            if not auth_key:
                self.state.note = "Generating Headscale auth key..."
                self.state._broadcast()
                auth_key = await get_headscale_auth_key()
                set_env("SPARKSTACK_HEADSCALE_AUTH_KEY", auth_key)

            await deploy_head_sidecar()

            if not SPARKSTACK_HEAD_TAILNET_IP:
                self.state.note = "Resolving head Tailnet IP..."
                self.state._broadcast()
                ip = await resolve_tailnet_ip("sparkstack-head-sidecar")
                set_env("SPARKSTACK_HEAD_TAILNET_IP", ip)

            # --- Worker sidecars ---
            from sparkstack.core.env import (  # noqa: PLC0415
                SPARK_NODE_TARGET,
                WORKER_TAILNET_IP,
                get_headscale_url,
            )

            headscale_url = get_headscale_url()
            worker_targets = [
                (SPARK_NODE_TARGET, "WORKER_TAILNET_IP", "Spark Worker"),
            ]

            for target, ip_env_key, label in worker_targets:
                if not target:
                    continue
                ssh_target = target.replace("ssh://", "")
                self.state.note = f"Deploying worker sidecar on {label}..."
                self.state._broadcast()

                try:
                    await deploy_worker_sidecar(ssh_target, auth_key, headscale_url)
                except RuntimeError as e:
                    # Non-fatal: sidecar may already be running and authenticated
                    logger.warning(f"Worker sidecar deployment note for {label}: {e}")

                # Verify health
                healthy = await poll_sidecar_health(ssh_target)
                if healthy:
                    logger.info(f"  ✅ Worker sidecar on {label} is healthy.")
                else:
                    logger.warning(
                        f"  ⚠️ Worker sidecar on {label} may need manual attention."
                    )

                # Resolve and persist the worker's Tailnet IP
                if not WORKER_TAILNET_IP:
                    self.state.note = f"Resolving Tailnet IP for {label}..."
                    self.state._broadcast()
                    try:
                        worker_ip = await resolve_tailnet_ip(ssh_target)
                        set_env(ip_env_key, worker_ip)
                        logger.info(f"  📍 {label} Tailnet IP: {worker_ip}")
                    except Exception as e:
                        logger.warning(
                            f"Could not resolve Tailnet IP for {label}: {e}. "
                            f"Set {ip_env_key} manually in .env."
                        )

        except Exception as e:
            self.state.fail(f"Failed to deploy sidecars: {e}")
            raise


class InferenceStackService(Service):
    dependencies = ["SparkRun", "Monitoring", "OpenClaw"]

    async def update(self) -> None:
        current_stack = (self.settings.project_root / "current").resolve()
        if not current_stack.exists():
            self.state.fail("No active stack found in 'current/'")
            return

        env = os.environ.copy()
        if SPARK_NODE_TARGET:
            if "://" in SPARK_NODE_TARGET:
                env["DOCKER_HOST"] = SPARK_NODE_TARGET
            else:
                env["DOCKER_CONTEXT"] = SPARK_NODE_TARGET

        self.progress.begin_phases(4 if self.settings.pull_latest else 3)
        phase_num = 1

        phase_num = await self._pull_images(
            current_stack,
            phase_num,
            task_name="Pulling litellm gateway",
            project_name="current",
            env=env,
        )

        # Always rebuild configs from stack.yaml to pick up builder changes.
        self.progress.phase(phase_num, "Rebuilding configs")
        self.state.set_task("Rebuilding configs", 40)
        stack_yaml = current_stack / "stack.yaml"
        if stack_yaml.exists():
            await StackBuilder.rebuild_from_stack(current_stack)
        self.progress.phase_end()
        phase_num += 1

        self.progress.phase(phase_num, "Restarting stack")
        self.state.set_task("Restarting stack", 60)

        if stack_yaml.exists():
            await launch_stack(current_stack, rebuild_images=self.settings.pull_latest, env=env)
        else:
            compose_yaml = current_stack / "docker-compose.yaml"
            if compose_yaml.exists():
                await self.run_compose(
                    current_stack,
                    "up",
                    "-d",
                    "--build",
                    "--remove-orphans",
                    project_name="current",
                    env=env,
                )
        self.progress.phase_end()
        phase_num += 1

        # Use centralized health manager with explicit probes
        litellm_key = os.getenv("LITELLM_MASTER_KEY", "sk-sparkstack-default-master-key")
        target_host = WORKER_TAILNET_IP if WORKER_TAILNET_IP else "localhost"
        manager = ServiceHealthManager(
            "litellm",
            env=env,
            probes=[
                DockerProbe("litellm", env=env),
                LogProbe("litellm", env=env),
                HttpProbe(
                    f"http://{target_host}:4000/health",
                    headers={"Authorization": f"Bearer {litellm_key}"},
                ),
            ],
        )
        await self._probe_health(phase_num, manager, timeout=60, fail_msg="Health check timed out")


class MonitoringService(Service):
    async def update(self) -> None:
        from sparkstack.core.env import (  # noqa: PLC0415
            MONITORING_NODE_TARGET,
            is_monitoring_external,
        )

        mon_dir = self.settings.project_root / "services" / "monitoring"
        stack_dir = self.settings.project_root / "current"

        # Ensure the stack dir exists before writing configs.
        # `current` is normally a symlink to the active stack version.
        # If it's a dangling symlink (target was deleted), resolve the target
        # and create that directory so the symlink becomes valid again.
        if not stack_dir.exists():
            target = stack_dir.resolve()
            target.mkdir(parents=True, exist_ok=True)
        MonitoringBuilder(stack_dir).write(preserve_targets=True)

        env = os.environ.copy()
        # Inject SPARKSTACK_DIR for compose
        env["SPARKSTACK_DIR"] = str(stack_dir.resolve())

        if MONITORING_NODE_TARGET:
            if "://" in MONITORING_NODE_TARGET:
                env["DOCKER_HOST"] = MONITORING_NODE_TARGET
            else:
                env["DOCKER_CONTEXT"] = MONITORING_NODE_TARGET

        if is_monitoring_external():
            compose_file = "docker-compose.external.yml"
            mode_label = "agent-only (external monitoring)"
        else:
            compose_file = "docker-compose.yml"
            mode_label = "full stack (managed monitoring)"

        logger.info(f"Deploying monitoring in {mode_label} mode")

        self.progress.begin_phases(3 if self.settings.pull_latest else 2)
        phase_num = 1

        phase_num = await self._pull_images(mon_dir, phase_num, env=env)

        phase_num = await self._deploy_compose(
            mon_dir,
            phase_num,
            compose_args=["-f", compose_file],
            up_args=["-d", "--build"],
            env=env,
        )

        manager = ServiceHealthManager(
            "vllm-progress-manager", probes=[HttpProbe("http://localhost:8126/status", timeout=2.0)]
        )
        await self._probe_health(
            phase_num, manager, timeout=60, fail_msg="Monitoring telemetry health check timed out"
        )


class RegistrySyncService(Service):
    dependencies = ["InferenceStack"]

    async def update(self) -> None:
        self.state.set_task("Syncing models to gateway", 50)

        await sync_registry(project_root=self.settings.project_root)
        self.state.complete()


class OpenClawService(UpdaterService):
    dependencies = []
    updater_class = OpenClawUpdater
