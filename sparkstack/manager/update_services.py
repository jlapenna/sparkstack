#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
"""
update_services.py - Modern, async-first service orchestration.
"""

import argparse
import asyncio
import os
import signal
import sys
from contextlib import suppress
from contextvars import ContextVar
from pathlib import Path

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sparkstack.core.env import PROJECT_ROOT
from sparkstack.core.ipc_server import (
    ExitEvent,
    IPCServer,
    LogEvent,
)
from sparkstack.core.schemas import ServiceStatus
from sparkstack.core.statsd import StatsdClient
from sparkstack.core.utils.locking import run_with_lock
from sparkstack.manager.orchestration_utils import cleanup_zombies, pre_flight_checks
from sparkstack.manager.services import (
    CloudflareService,
    HeadscaleService,
    InferenceStackService,
    MonitoringService,
    OpenClawService,
    RegistrySyncService,
    Service,
    ServiceState,
    SparkrunService,
)
from sparkstack.manager.wait_for_backends import wait_for_backends_to_load

current_service: ContextVar[str] = ContextVar("current_service", default="")

STATSD_HOST = os.environ.get("SPARKRUN_STATSD_HOST", "127.0.0.1")
STATSD_PORT = int(os.environ.get("SPARKRUN_STATSD_PORT", "8125"))
STATSD_ADDR = (STATSD_HOST, STATSD_PORT)

statsd = StatsdClient(host=STATSD_HOST, port=STATSD_PORT, protocol="udp")


class Settings(BaseSettings):
    """Global configuration for service updates."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    project_root: Path = Field(default_factory=lambda: PROJECT_ROOT)
    pull_latest: bool = False
    target_services: tuple[str, ...] | None = None
    sparkstack_enabled_services: str | None = Field(
        default=None, validation_alias="SPARKSTACK_ENABLED_SERVICES"
    )

    def model_post_init(self, __context) -> None:
        if self.target_services is None and self.sparkstack_enabled_services:
            svcs = [s.strip() for s in self.sparkstack_enabled_services.split(",") if s.strip()]
            if svcs:
                self.target_services = tuple(svcs)


SOCKET_PATH = "/tmp/sparkstack.sock"


class Orchestrator:
    def __init__(self, settings: Settings, ipc=None):
        self.settings = settings
        self._ipc = ipc
        self.states = {
            "SparkRun": ServiceState("SparkRun", ipc=ipc, statsd=statsd),
            "Cloudflare": ServiceState("Cloudflare", ipc=ipc, statsd=statsd),
            "Headscale": ServiceState("Headscale", ipc=ipc, statsd=statsd),
            "InferenceStack": ServiceState("InferenceStack", ipc=ipc, statsd=statsd),
            "RegistrySync": ServiceState("RegistrySync", ipc=ipc, statsd=statsd),
            "Monitoring": ServiceState("Monitoring", ipc=ipc, statsd=statsd),
            "OpenClaw": ServiceState("OpenClaw", ipc=ipc, statsd=statsd),
        }
        self.services = [
            SparkrunService("SparkRun", self.states["SparkRun"], settings),
            CloudflareService("Cloudflare", self.states["Cloudflare"], settings),
            HeadscaleService("Headscale", self.states["Headscale"], settings),
            InferenceStackService("InferenceStack", self.states["InferenceStack"], settings),
            RegistrySyncService("RegistrySync", self.states["RegistrySync"], settings),
            MonitoringService("Monitoring", self.states["Monitoring"], settings),
            OpenClawService("OpenClaw", self.states["OpenClaw"], settings),
        ]

    async def run_service(self, service: Service, semaphore: asyncio.Semaphore):
        """Wait for dependencies then run the service update."""
        current_service.set(service.name)

        if self.settings.target_services:
            target_lower = {s.lower() for s in self.settings.target_services}
            if service.name.lower() not in target_lower:
                service.state.status = ServiceStatus.SKIPPED
                service.state.note = "Skipped"
                service.state.done_event.set()
                service.state._broadcast()
                return

        try:
            for dep_name in service.dependencies:
                dep_state = self.states.get(dep_name)
                if not dep_state:
                    raise ValueError(
                        f"Service {service.name} depends on unknown service {dep_name}"
                    )

                # Wait for the dependency to finish (Complete, Failed or Skipped)
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

    async def run(self) -> bool:
        """Run orchestration. Returns True on success, False on failure."""
        if self.settings.target_services:
            target_lower = {s.lower() for s in self.settings.target_services}
            valid_names = {s.name.lower() for s in self.services}
            invalid = target_lower - valid_names
            if invalid:
                logger.error(f"Unknown services to update: {', '.join(invalid)}")
                if self._ipc is not None:
                    self._ipc.broadcast_event(
                        ExitEvent(
                            success=False,
                            message=f"Unknown services to update: {', '.join(invalid)}",
                        )
                    )
                return False

        logger.info(
            f"Starting Orchestrated Update (Pull: {'ON' if self.settings.pull_latest else 'OFF'})"
        )

        semaphore = asyncio.Semaphore(2)  # Limit concurrent Docker/heavy I/O operations
        tasks = [asyncio.create_task(self.run_service(s, semaphore)) for s in self.services]

        async def orchestration_runner():
            try:
                await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    t.cancel()
            except Exception:
                pass

        runner_task = asyncio.create_task(orchestration_runner())

        # Await the orchestration completion headlessly
        await runner_task

        failed_services = [s for s in self.services if s.state.status == ServiceStatus.FAILED]
        if failed_services:
            logger.error("Orchestration failed due to service errors:")
            for svc in failed_services:
                logger.error(f"  • {svc.name}: {svc.state.error or svc.state.note}")

            if self._ipc is not None:
                self._ipc.broadcast_event(
                    ExitEvent(
                        success=False,
                        message="Some services failed",
                    )
                )
            return False

        logger.info("All services processed.")

        stack_dir = self.settings.project_root / "current"
        if stack_dir.exists():
            logger.info("Waiting for updated backends to initialize and load models...")
            await wait_for_backends_to_load(stack_dir, ipc_server=self._ipc)

        if self._ipc is not None:
            self._ipc.broadcast_event(
                ExitEvent(
                    success=True,
                    message="All services processed and models loaded",
                )
            )
        return True


async def main():

    parser = argparse.ArgumentParser(description="Professional service updater.")
    parser.add_argument("--pull-latest", action="store_true", help="Pull latest images.")
    parser.add_argument("services", nargs="*", help="Specific services to update")
    args = parser.parse_args()

    settings = Settings(
        pull_latest=args.pull_latest,
        target_services=tuple(args.services) if args.services else None,
    )

    # Configure loguru to be less noisy for console, but keep everything in file
    logger.remove()
    logger.add("update_services.log", level="DEBUG")
    # Add a fallback stderr sink so we don't run totally blind without UI
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    try:
        async with IPCServer.serve(SOCKET_PATH) as ipc:
            # IPC logging sink
            def _ipc_log_sink(message):
                record = message.record
                service = record["extra"].get("service") or current_service.get() or None
                phase = record["extra"].get("phase")
                ipc.broadcast_event(
                    LogEvent(
                        level=record["level"].name,
                        message=str(record["message"]),
                        timestamp=record["time"].isoformat(),
                        service=service,
                        phase=phase,
                    )
                )

            logger.add(_ipc_log_sink, level="INFO", format="{message}")

            # Now we can safely run early checks and they will be broadcast
            await pre_flight_checks(settings)
            await cleanup_zombies(settings)

            orchestrator = Orchestrator(settings, ipc=ipc)

            def ui_sink(msg):
                svc_name = current_service.get()
                if svc_name and hasattr(orchestrator, "states") and svc_name in orchestrator.states:
                    text = msg.record["message"].split("\n")[0]
                    prefix = f"[{svc_name}] "
                    if text.startswith(prefix):
                        text = text[len(prefix) :]
                    orchestrator.states[svc_name].note = text

            logger.add(ui_sink, level="INFO")

            success = await orchestrator.run()
    finally:
        await statsd.close()

    if not success:
        sys.exit(1)


async def _run_main_with_signals():
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()

    if main_task:
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, main_task.cancel)

    try:
        await main()
    except asyncio.CancelledError:
        print("\nAborted by user.")
        sys.exit(1)
    except SystemExit as e:
        sys.exit(e.code)
    except Exception:
        logger.exception("Global failure")
        sys.exit(1)


if __name__ == "__main__":
    run_with_lock(".sparkstack-update-services.lock", _run_main_with_signals())
