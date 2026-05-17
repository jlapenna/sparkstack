"""sparkstack sync-dashboards — push dashboard JSONs to a remote Grafana."""

from __future__ import annotations

import click

from sparkstack.manager.sync_dashboards import sync_dashboards

from . import main
from ._common import json_option, run_async, setup_command_logging


@main.command("sync-dashboards")
@click.option(
    "--target",
    default=None,
    help="Grafana base URL (e.g. http://monitor.lan:3001). "
    "Defaults to REMOTE_GRAFANA_URL derived from SPARK_MONITORING_HOST.",
)
@click.option(
    "--api-key",
    default=None,
    envvar="GRAFANA_API_KEY",
    help="Grafana API key or service-account token. "
    "Falls back to GRAFANA_API_KEY env var.",
)
@click.option(
    "--folder",
    default="sparkstack",
    show_default=True,
    help="Grafana folder to place dashboards in.",
)
@json_option()
@click.pass_context
def sync_dashboards_cmd(
    ctx: click.Context,
    target: str | None,
    api_key: str | None,
    folder: str,
    output_json: bool,
) -> None:
    """Sync local Grafana dashboard definitions to a remote Grafana instance."""
    setup_command_logging(output_json, ctx.obj.get("verbose", 0))
    run_async(_sync_async(target=target, api_key=api_key, folder=folder))


async def _sync_async(
    *,
    target: str | None,
    api_key: str | None,
    folder: str,
) -> None:
    await sync_dashboards(target=target, api_key=api_key, folder=folder)
