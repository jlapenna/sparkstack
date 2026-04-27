#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
import sys
from pathlib import Path

from loguru import logger

from core.env import PROJECT_ROOT as ROOT_DIR
from core.env import STACKS_DIR

# Add root directory to path to allow importing core
from core.utils import async_run_command


async def main():
    parser = argparse.ArgumentParser(description="Switch active stack and restart services")
    parser.add_argument(
        "target",
        help="Directory name of the target stack (e.g., spark-stack-registry/stacks/powerhouse-maximize-20260330)",
    )
    args = parser.parse_args()

    target_str = args.target

    # Resolve absolute path if target is relative
    if not target_str.startswith("/"):
        if target_str.startswith("spark-stack-registry/stacks/"):
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

    # Stop existing stack
    logger.info("Stopping existing stack...")
    await async_run_command(["systemctl", "--user", "stop", "vllm-active.service"], check=False)

    # Kill orphaned sparkrun and vllm containers explicitly to prevent OOM
    logger.info("Cleaning up lingering containers...")
    ps_result = await async_run_command(
        ["docker", "ps", "-a", "-q", "-f", "name=sparkrun|vllm|nemotron|llama|qwen"], check=False
    )
    if ps_result.stdout:
        containers = ps_result.stdout.split()
        if containers:
            await async_run_command(["docker", "rm", "-f"] + containers, check=False)

    # Force kill orphaned vLLM/EngineCore processes that may survive container removal
    # This is critical on Blackwell to free up squatting RAM (The "Zombie Protocol")
    logger.info("Purging orphaned VLLM/EngineCore processes...")
    await async_run_command(["pkill", "-9", "-f", "VLLM|sparkrun|vllm"], check=False)

    # Clean up obsolete networks
    await async_run_command(["docker", "network", "prune", "-f"], check=False)
    net_inspect = await async_run_command(
        ["docker", "network", "inspect", "vllm-network"], check=False
    )
    if net_inspect.returncode != 0:
        await async_run_command(["docker", "network", "create", "vllm-network"], check=False)

    # Force remove vllm-gateway to prevent naming conflicts during fast swaps
    await async_run_command(["docker", "rm", "-f", "vllm-gateway"], check=False)

    # Update symlink
    logger.info(f"Switching active stack to: {args.target}")
    symlink_path = ROOT_DIR / "current"

    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()
    symlink_path.symlink_to(full_target)

    # Start new service
    logger.info("Starting new stack...")
    launch_script = full_target / "launch.sh"
    if launch_script.is_file():
        logger.info("🚀 Using hybrid launcher (sparkrun + compose)...")
        res = await async_run_command(
            [str(launch_script)], cwd=full_target, check=False, capture_output=True
        )
        if res.stdout:
            for line in res.stdout.splitlines():
                logger.info(f"[launch.sh] {line}")
        if res.stderr:
            for line in res.stderr.splitlines():
                logger.error(f"[launch.sh] {line}")
        if res.returncode != 0:
            logger.error(f"Launch script failed with code {res.returncode}")
            sys.exit(res.returncode)
    else:
        logger.info("📦 Using standard docker compose launcher...")
        await async_run_command(["systemctl", "--user", "daemon-reload"], check=False)
        await async_run_command(
            ["systemctl", "--user", "start", "vllm-active.service"], check=False
        )

    # Recreate Prometheus
    logger.info("🔄 Refreshing monitoring stack...")
    monitor_compose = ROOT_DIR / "services" / "monitoring" / "docker-compose.yml"
    await async_run_command(
        ["docker", "compose", "-f", str(monitor_compose), "rm", "-fsv", "prometheus"], check=False
    )
    await async_run_command(
        ["docker", "compose", "-f", str(monitor_compose), "up", "-d"], check=False
    )

    # Recreate Cloudflare tunnel
    logger.info("🔄 Refreshing Cloudflare tunnel...")
    cf_dir = ROOT_DIR / "cloudflare"
    if cf_dir.is_dir():
        tunnel_down = cf_dir / "tunnel.sh"
        if tunnel_down.exists():
            await async_run_command([str(tunnel_down), "down"], cwd=cf_dir, check=False)
            await async_run_command([str(tunnel_down), "up", "-d"], cwd=cf_dir, check=False)

    logger.info(f"✅ Active stack is now: {args.target}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<level>{message}</level>")
    asyncio.run(main())
