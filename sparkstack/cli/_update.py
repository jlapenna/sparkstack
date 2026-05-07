"""sparkstack update — run the full service orchestration pipeline."""

from __future__ import annotations

import sys

import click
from loguru import logger

from sparkstack.core.ipc_server import IPCServer, LogEvent, event_adapter
from sparkstack.manager.orchestration_utils import cleanup_zombies, pre_flight_checks
from sparkstack.manager.update_services import (
    SOCKET_PATH,
    Orchestrator,
    Settings,
    current_service,
)

from . import main
from ._common import json_option, run_async, with_process_lock


@main.command("update")
@click.option("--pull-latest", is_flag=True, default=False, help="Pull latest container images.")
@click.argument("services", nargs=-1)
@json_option()
@with_process_lock("update-services")
@click.pass_context
def update(
    ctx: click.Context, pull_latest: bool, output_json: bool, services: tuple[str, ...]
) -> None:
    """Run the full service update orchestration.

    Syncs the registry, builds/updates OpenClaw and SparkRun,
    launches the stack, and waits for backends to load.

    Provide optional SERVICES to limit the update to only those services (e.g. openclaw).

    Use --json for structured output suitable for piping into scripts.
    """
    run_async(_update_async(pull_latest=pull_latest, output_json=output_json, services=services))


async def _update_async(*, pull_latest: bool, output_json: bool, services: tuple[str, ...]) -> None:
    settings = Settings(pull_latest=pull_latest, target_services=services if services else None)

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
                event = LogEvent(
                    level=record["level"].name,
                    message=str(record["message"]),
                    timestamp=record["time"].isoformat(),
                    service=service,
                    phase=phase,
                )
                sys.stdout.write(event_adapter.dump_json(event).decode() + "\n")
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

        success = await orchestrator.run()

    if not success:
        raise SystemExit(1)
