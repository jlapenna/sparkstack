import asyncio
import sys
from pathlib import Path

import yaml
from loguru import logger

from sparkstack.core.env import is_monitoring_external
from sparkstack.core.utils import async_run_command, async_run_compose


async def launch_stack(
    stack_dir: Path, *, rebuild_images: bool = False, env: dict[str, str] | None = None
) -> None:
    repo_root = Path(__file__).parent.parent.parent.resolve()
    stack_yaml_path = stack_dir / "stack.yaml"

    if not stack_yaml_path.exists():
        logger.error(f"❌ Error: {stack_yaml_path} not found.")
        raise FileNotFoundError(f"{stack_yaml_path} not found.")

    with open(stack_yaml_path) as f:
        stack = yaml.safe_load(f)

    # Soft launch: Compose handles gateway/monitoring natively. Only recreate backends manually.
    logger.info("🧹 Removing stale backend containers...")

    # Find all currently running sparkstack backends
    try:
        result = await async_run_command(
            ["docker", "ps", "-aq", "--filter", "label=sparkstack-backend=true"],
            check=False,
            capture_output=True,
            env=env,
        )
        stale_containers = result.stdout.strip().split() if result.stdout else []
        if stale_containers:
            await async_run_command(
                ["docker", "rm", "-f"] + stale_containers,
                check=False,
                env=env,
            )
    except Exception as e:
        logger.warning(f"Failed to query or remove stale backends: {e}")

    # Launch backends
    logger.info("🚀 Launching model instances via sparkrun...")
    global_network = "sparkstack-net"

    for backend in stack.get("backends", []):
        recipe = backend["recipe"]
        if recipe.startswith("@"):
            recipe_path = recipe
        else:
            recipe_path = repo_root / "sparkstack-registry" / recipe
        cmd = [
            "uv",
            "run",
            "sparkrun",
            "run",
            str(recipe_path),
            "--hosts",
            backend.get("target", "localhost"),
            "--port",
            str(backend.get("port", 8000)),
            "--tp",
            str(backend.get("tensor_parallel", 1)),
            "--served-model-name",
            backend["name"],
            "--cluster",
            backend["name"],
            "--container-name",
            backend["name"],
            "--no-follow",
            "-o",
            f"network={global_network}",
            "--label",
            "sparkstack-backend=true",
        ]

        if rebuild_images:
            cmd.append("--rebuild")

        if "memory_limit" in backend:
            cmd.extend(["--memory-limit", backend["memory_limit"]])

        # Append overrides
        overrides = backend.get("overrides", {}).copy()

        # Pull out explicit flags if present in overrides
        if "gpu_memory_utilization" in overrides:
            cmd.extend(["--gpu-mem", str(overrides.pop("gpu_memory_utilization"))])
        if "max_model_len" in overrides:
            cmd.extend(["--max-model-len", str(overrides.pop("max_model_len"))])

        for key, value in overrides.items():
            cmd.extend(["-o", f"{key}={value}"])

        # Append environment variables
        for key, value in backend.get("env", {}).items():
            cmd.extend(["-o", f"env.{key}={value}"])

        for lbl in backend.get("labels", []):
            cmd.extend(["--label", lbl])

        await async_run_command(cmd, cwd=repo_root, capture_output=False, env=env)

    # Launch compose services
    external = is_monitoring_external()
    if external:
        logger.info("📦 Starting gateway + monitoring agents (external mode) via docker compose...")
    else:
        logger.info("📦 Starting gateway and monitoring via docker compose...")

    compose_file = "docker-compose.yaml"
    compose_args = ["-f", str(stack_dir / compose_file)]

    # In external mode, layer the agent-only monitoring compose on top
    monitoring_dir = repo_root / "services" / "monitoring"
    if external:
        compose_args.extend(["-f", str(monitoring_dir / "docker-compose.external.yml")])

    await async_run_compose(
        stack_dir,
        *compose_args,
        "up",
        "-d",
        "--build",
        project_root=repo_root,
        project_name="current",
        env=env,
    )
    logger.info("✅ Stack is operational.")


async def main():
    if len(sys.argv) < 2:
        print("❌ Error: stack directory not provided.")
        sys.exit(1)

    stack_dir = Path(sys.argv[1]).resolve()
    await launch_stack(stack_dir)


if __name__ == "__main__":
    asyncio.run(main())
