"""sparkstack update-monitoring — check and update monitoring container versions."""

from __future__ import annotations

import click

from sparkstack.manager.update_monitoring import main as monitoring_main

from . import main
from ._common import run_async, with_process_lock


@main.command("update-monitoring")
@with_process_lock("update-monitoring")
@click.pass_context
def update_monitoring(ctx: click.Context) -> None:
    """Check for and apply monitoring stack version updates.

    Queries GitHub, GCR, and Docker Hub for the latest versions of
    Prometheus, Grafana, and Alloy, then updates the compose file.
    """
    run_async(_update_monitoring_async())


async def _update_monitoring_async() -> None:
    await monitoring_main()
