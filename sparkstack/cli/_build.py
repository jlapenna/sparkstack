"""sparkstack build — build a stack from a registry recipe."""

from __future__ import annotations

import click

from sparkstack.core.builders.stack import StackBuilder
from sparkstack.core.schemas import ModelRequest

from . import main
from ._common import json_option, run_async, setup_command_logging


@main.command("build")
@click.argument("stack_name")
@click.argument("models", nargs=-1, required=True)
@click.option(
    "--allow-no-embedding",
    is_flag=True,
    default=False,
    help="Allow building a stack without an embedding model.",
)
@json_option()
@click.pass_context
def build(
    ctx: click.Context,
    stack_name: str,
    models: tuple[str, ...],
    allow_no_embedding: bool,
    output_json: bool,
) -> None:
    """Build a stack from a registry recipe.

    STACK_NAME is the unique identifier for the new stack.
    MODELS is one or more model names or aliases to include.
    """
    setup_command_logging(output_json, ctx.obj.get("verbose", 0))
    run_async(
        StackBuilder(
            stack_name,
            [ModelRequest.from_cli_arg(m) for m in models],
            allow_no_embedding=allow_no_embedding,
        ).build()
    )
