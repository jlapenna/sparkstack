"""sparkstack set-current — switch the active stack symlink and restart services."""

from __future__ import annotations

import click

from sparkstack.manager.set_current import switch_stack

from . import main
from ._common import json_option, resolve_stack_dir, run_async, setup_command_logging


@main.command("set-current")
@click.argument("target")
@click.option(
    "--no-launch",
    is_flag=True,
    default=False,
    help="Skip auto-launch after symlink switch.",
)
@json_option()
@click.pass_context
def set_current(ctx: click.Context, target: str, no_launch: bool, output_json: bool) -> None:
    """Switch the active stack and restart services.

    TARGET is a stack name (resolved under sparkstack-registry/stacks/)
    or an absolute path to a stack directory.
    """
    stack_dir = resolve_stack_dir(target)

    if not stack_dir.is_dir():
        raise click.BadParameter(f"Directory {stack_dir} does not exist.", param_hint="TARGET")

    setup_command_logging(output_json, ctx.obj.get("verbose", 0))

    run_async(switch_stack(stack_dir, no_launch=no_launch))
