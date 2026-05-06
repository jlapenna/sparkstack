"""sparkstack check — inspection sub-group (memory law, etc.)."""

from __future__ import annotations

import click

from sparkstack.manager.check_memory_law import main as memory_main

from . import main
from ._common import json_option, run_async, setup_command_logging


@main.group("check")
@click.pass_context
def check(ctx: click.Context) -> None:
    """Run system compliance checks."""


@check.command("memory")
@json_option()
@click.pass_context
def check_memory(ctx: click.Context, output_json: bool) -> None:
    """Audit memory usage against the memory law budget.

    Compares active Docker container RAM + estimated VRAM usage
    against the host's configured limits.
    """
    setup_command_logging(output_json, ctx.obj.get("verbose", 0))
    run_async(_check_memory_async())


async def _check_memory_async() -> None:
    await memory_main()
