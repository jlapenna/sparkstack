"""sparkstack update — run the full service orchestration pipeline."""

from __future__ import annotations

import json
import sys

import click
from loguru import logger

from sparkstack.core.ipc_server import IPCServer, LogEvent
from sparkstack.manager.orchestration_utils import cleanup_zombies, pre_flight_checks
from sparkstack.manager.update_services import (
    SOCKET_PATH,
    Orchestrator,
    Settings,
    current_service,
)
from sparkstack.manager.wait_for_backends import wait_for_backends_to_load

from . import main
from ._common import json_option, run_async, with_process_lock


@main.command("update")
@click.option("--pull-latest", is_flag=True, default=False, help="Pull latest container images.")
@json_option()
@with_process_lock("update-services")
@click.pass_context
def update(ctx: click.Context, pull_latest: bool, output_json: bool) -> None:
    """Run the full service update orchestration.

    Syncs the registry, builds/updates OpenClaw and SparkRun,
    launches the stack, and waits for backends to load.

    Use --json for structured output suitable for piping into scripts.
    """
    run_async(_update_async(pull_latest=pull_latest, output_json=output_json))


async def _update_async(*, pull_latest: bool, output_json: bool) -> None:
    settings = Settings(pull_latest=pull_latest)

    # Configure logging: file always, stderr only when not --json
    logger.remove()
    logger.add("update_services.log", level="DEBUG")
    if not output_json:
        logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    async with IPCServer.serve(SOCKET_PATH) as ipc:

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

        # JSON sink — structured events to stdout for scripting
        if output_json:

            def _json_sink(message):
                record = message.record
                service = current_service.get() or None
                phase = record["extra"].get("phase")
                event = {
                    "event_type": "log",
                    "level": record["level"].name,
                    "message": str(record["message"]),
                    "timestamp": record["time"].isoformat(),
                    "service": service,
                    "phase": phase,
                }
                sys.stdout.write(json.dumps(event) + "\n")
                sys.stdout.flush()

            logger.add(_json_sink, level="INFO", format="{message}")

        # Pre-flight and zombie cleanup are now captured by all sinks
        await pre_flight_checks(settings)
        await cleanup_zombies(settings)

        orchestrator = Orchestrator(settings, ipc=ipc)

        def _ui_note_sink(msg):
            """Update service state notes for TUI display."""
            svc_name = current_service.get()
            if svc_name and svc_name in orchestrator.states:
                text = msg.record["message"].split("\n")[0]
                orchestrator.states[svc_name].note = text

        logger.add(_ui_note_sink, level="INFO")

        await orchestrator.run()

    # Post-orchestration: wait for backends
    stack_dir = settings.project_root / "current"
    if stack_dir.exists():
        logger.info("Waiting for updated backends to initialize and load models...")
        await wait_for_backends_to_load(stack_dir)
