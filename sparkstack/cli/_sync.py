"""sparkstack sync-registry — sync models.json into openclaw config."""

from __future__ import annotations

import click

from sparkstack.manager.sync_registry import sync_registry

from . import main
from ._common import json_option, run_async, setup_command_logging


@main.command("sync-registry")
@json_option()
@click.pass_context
def sync_registry_cmd(ctx: click.Context, output_json: bool) -> None:
    """Sync the model registry into the OpenClaw configuration."""
    setup_command_logging(output_json, ctx.obj.get("verbose", 0))
    run_async(_sync_async())


async def _sync_async() -> None:
    await sync_registry()
