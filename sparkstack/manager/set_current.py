#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from sparkstack.core.env import PROJECT_ROOT as ROOT_DIR
from sparkstack.core.env import STACKS_DIR, is_monitoring_external

# Add root directory to path to allow importing core
from sparkstack.core.utils import async_run_command, async_run_compose
from sparkstack.manager.launch import launch_stack


async def main():
    parser = argparse.ArgumentParser(description="Switch active stack and restart services")
    parser.add_argument(
        "target",
        help="Directory name of the target stack (e.g., sparkstack-registry/stacks/powerhouse-maximize-20260330)",
    )
    args = parser.parse_args()

    target_str = args.target

    # Resolve absolute path if target is relative
    if not target_str.startswith("/"):
        if target_str.startswith("sparkstack-registry/stacks/"):
            full_target = ROOT_DIR / target_str
        else:
            full_target = STACKS_DIR / target_str
    else:
        full_target = Path(target_str)

    try:
        full_target = full_target.resolve()
        if not full_target.is_relative_to(ROOT_DIR):
            logger.error(f"❌ Error: Target directory {full_target} escapes ROOT_DIR {ROOT_DIR}.")
            sys.exit(1)
    except ValueError as e:
        logger.error(f"❌ Error resolving target path: {e}")
        sys.exit(1)

    if not full_target.is_dir():
        logger.error(f"❌ Error: Directory {full_target} does not exist.")
        sys.exit(1)

    # --- Two-tier remote teardown ---
    # Must happen before local container cleanup so sparkrun can update its own
    # metadata before we touch any containers.
    current_stack = ROOT_DIR / "current"
    if current_stack.is_symlink() or current_stack.exists():
        outgoing_stack = current_stack.resolve()
        if outgoing_stack.is_dir():
            from sparkstack.core.env import SPARKRUN_CMD  # noqa: PLC0415
            from sparkstack.manager.remote import (  # noqa: PLC0415
                read_sidecar_state,
                teardown_sidecars,
            )

            state = read_sidecar_state(outgoing_stack)
            cluster_name = state.get("cluster_name", "")

            # Tier 1: Let sparkrun stop all backends and clean its own metadata.
            if cluster_name:
                logger.info(
                    f"🧹 Tier 1: Stopping remote sparkrun backends (cluster: {cluster_name})..."
                )
                await async_run_command(
                    [*SPARKRUN_CMD, "stop", "--all", "--cluster", cluster_name],
                    check=False,
                )

            # Tier 2: Remove Tailscale sidecars for hosts no longer needed.
            if state.get("sidecars"):
                logger.info("🧹 Tier 2: Tearing down remote Tailscale sidecars...")
                await teardown_sidecars(outgoing_stack, hosts_to_keep=set())

    # Kill orphaned sparkrun and vllm containers explicitly to prevent OOM
    logger.info("Cleaning up lingering local containers...")
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
    logger.info(f"Switching active stack to: {args.target}")
    symlink_path = ROOT_DIR / "current"

    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()
    symlink_path.symlink_to(full_target)

    # Start new service
    logger.info("Starting new stack...")
    stack_yaml = full_target / "stack.yaml"
    if stack_yaml.is_file():
        logger.info("🚀 Using hybrid launcher (sparkrun + compose)...")
        await launch_stack(full_target)
    else:
        logger.info("📦 Using standard docker compose launcher...")
        await async_run_command(["systemctl", "--user", "daemon-reload"], check=False)
        await async_run_command(
            ["systemctl", "--user", "start", "vllm-active.service"], check=False
        )

    logger.info("🔄 Refreshing monitoring stack...")
    monitor_dir = ROOT_DIR / "services" / "monitoring"
    compose_args = ["-f", "docker-compose.external.yml"] if is_monitoring_external() else []
    await async_run_compose(monitor_dir, "rm", "-fsv", "prometheus", check=False)
    await async_run_compose(monitor_dir, *compose_args, "up", "-d", check=False)

    # Recreate Cloudflare tunnel
    logger.info("🔄 Refreshing Cloudflare tunnel...")
    cf_dir = ROOT_DIR / "services" / "cloudflare"
    if cf_dir.is_dir():
        cf_compose = cf_dir / "docker-compose.yml"
        if cf_compose.exists():
            await async_run_compose(cf_dir, "down", project_root=ROOT_DIR, check=False)
            await async_run_compose(cf_dir, "up", "-d", project_root=ROOT_DIR, check=False)

    logger.info(f"✅ Active stack is now: {args.target}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{message}</level>")
    asyncio.run(main())
