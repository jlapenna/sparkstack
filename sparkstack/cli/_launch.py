"""sparkstack launch — start services for a stack."""

from __future__ import annotations

import click

from sparkstack.manager.launch import launch_stack

from . import main
from ._common import json_option, resolve_stack_dir, run_async, setup_command_logging


@main.command("launch")
@click.argument("stack_name", default="current")
@json_option()
@click.pass_context
def launch(ctx: click.Context, stack_name: str, output_json: bool) -> None:
    """Launch services for a stack.

    STACK_NAME defaults to "current" (the active symlink).
    """
    stack_dir = resolve_stack_dir(stack_name)

    if not stack_dir.is_dir():
        raise click.BadParameter(
            f"Stack directory {stack_dir} does not exist.", param_hint="STACK_NAME"
        )

    setup_command_logging(output_json, ctx.obj.get("verbose", 0))

    run_async(_launch_async(stack_dir))


async def _launch_async(stack_dir) -> None:
    await launch_stack(stack_dir)
