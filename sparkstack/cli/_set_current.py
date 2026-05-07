"""sparkstack set-current — switch the active stack symlink and restart services."""

from __future__ import annotations

import sys

import click
from loguru import logger

from sparkstack.core.env import PROJECT_ROOT as ROOT_DIR
from sparkstack.core.utils.shell import async_run_command, async_run_compose
from sparkstack.manager.launch import launch_stack

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

    run_async(_set_current_async(stack_dir, no_launch=no_launch))


async def _set_current_async(stack_dir, *, no_launch: bool) -> None:
    """Core async logic extracted from manager/set_current.py."""
    # Validate the target doesn't escape ROOT_DIR
    try:
        resolved = stack_dir.resolve()
        if not resolved.is_relative_to(ROOT_DIR):
            logger.error(f"❌ Error: Target directory {resolved} escapes ROOT_DIR {ROOT_DIR}.")
            sys.exit(1)
    except ValueError as e:
        logger.error(f"❌ Error resolving target path: {e}")
        sys.exit(1)

    # Stop existing stack
    logger.info("Stopping existing stack...")
    await async_run_command(["systemctl", "--user", "stop", "vllm-active.service"], check=False)

    # Kill orphaned containers
    logger.info("Cleaning up lingering containers...")
    ps_result = await async_run_command(
        ["docker", "ps", "-a", "-q", "-f", "name=sparkrun|vllm|nemotron|llama|qwen"], check=False
    )
    if ps_result.stdout:
        containers = ps_result.stdout.split()
        if containers:
            await async_run_command(["docker", "rm", "-f"] + containers, check=False)

    # Clean up obsolete networks
    await async_run_command(["docker", "network", "prune", "-f"], check=False)
    net_inspect = await async_run_command(
        ["docker", "network", "inspect", "vllm-network"], check=False
    )
    if net_inspect.returncode != 0:
        await async_run_command(["docker", "network", "create", "vllm-network"], check=False)

    # Force remove litellm to prevent naming conflicts during fast swaps
    await async_run_command(["docker", "rm", "-f", "litellm"], check=False)

    # Update symlink
    logger.info(f"Switching active stack to: {resolved.name}")
    symlink_path = ROOT_DIR / "current"
    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()
    symlink_path.symlink_to(resolved)

    # Launch new stack (unless --no-launch)
    if not no_launch:
        stack_yaml = resolved / "stack.yaml"
        if stack_yaml.is_file():
            logger.info("🚀 Using hybrid launcher (sparkrun + compose)...")
            await launch_stack(resolved)
        else:
            logger.info("📦 Using standard docker compose launcher...")
            await async_run_command(["systemctl", "--user", "daemon-reload"], check=False)
            await async_run_command(
                ["systemctl", "--user", "start", "vllm-active.service"], check=False
            )

    # Recreate Prometheus
    logger.info("🔄 Refreshing monitoring stack...")
    monitor_dir = ROOT_DIR / "services" / "monitoring"
    await async_run_compose(monitor_dir, "rm", "-fsv", "prometheus", check=False)
    await async_run_compose(monitor_dir, "up", "-d", check=False)

    # Recreate Cloudflare tunnel
    logger.info("🔄 Refreshing Cloudflare tunnel...")
    cf_dir = ROOT_DIR / "services" / "cloudflare"
    if cf_dir.is_dir():
        cf_compose = cf_dir / "docker-compose.yml"
        if cf_compose.exists():
            await async_run_compose(cf_dir, "down", project_root=ROOT_DIR, check=False)
            await async_run_compose(cf_dir, "up", "-d", project_root=ROOT_DIR, check=False)

    logger.info(f"✅ Active stack is now: {resolved.name}")
