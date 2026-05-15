"""sparkstack wait — poll backends until models are loaded."""

from __future__ import annotations

import sys

import click

from sparkstack.manager.wait_for_backends import wait_for_backends_to_load

from . import main
from ._common import json_option, resolve_stack_dir, run_async, setup_command_logging


@main.command("wait")
@click.option("--stack", default=None, help="Stack to wait for (default: current).")
@click.option("--timeout", type=int, default=1800, help="Timeout in seconds (default: 1800).")
@click.option(
    "--no-fail-fast",
    is_flag=True,
    default=False,
    help="Monitor mode: don't exit on crash.",
)
@json_option()
@click.pass_context
def wait(
    ctx: click.Context, stack: str | None, timeout: int, no_fail_fast: bool, output_json: bool
) -> None:
    """Wait for backend models to finish loading.

    Polls the vLLM status endpoints until all backends report ready,
    or until --timeout is reached.
    """
    stack_dir = resolve_stack_dir(stack)

    if not stack_dir.is_dir():
        raise click.BadParameter(f"Stack directory {stack_dir} does not exist.")

    setup_command_logging(output_json, ctx.obj.get("verbose", 0))

    run_async(_wait_async(stack_dir, timeout, fail_fast=not no_fail_fast, output_json=output_json))


async def _wait_async(stack_dir, timeout: int, *, fail_fast: bool, output_json: bool = False) -> None:
    success = await wait_for_backends_to_load(
        stack_dir, timeout, fail_fast=fail_fast, output_json=output_json
    )
    if not success:
        sys.exit(1)
