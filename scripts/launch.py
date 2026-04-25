import subprocess
import sys
from pathlib import Path

import yaml


def run_command(cmd, cwd=None):
    print(f"🚀 Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=cwd)


def main():
    if len(sys.argv) < 2:
        print("❌ Error: stack directory not provided.")
        sys.exit(1)

    stack_dir = Path(sys.argv[1]).resolve()
    repo_root = Path(__file__).parent.parent.resolve()
    stack_yaml_path = stack_dir / "stack.yaml"

    if not stack_yaml_path.exists():
        print(f"❌ Error: {stack_yaml_path} not found.")
        sys.exit(1)

    with open(stack_yaml_path) as f:
        stack = yaml.safe_load(f)

    # Clean up old instances
    print("🧹 Cleaning up old containers...")
    subprocess.run(
        ["docker", "rm", "-f", "vllm-gateway", "vllm-progress"]
        + [b["name"] + "_solo" for b in stack.get("backends", [])],
        stderr=subprocess.DEVNULL,
    )

    parent_env = repo_root / ".env"
    subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(parent_env),
            "-f",
            str(stack_dir / "docker-compose.yaml"),
            "down",
            "--remove-orphans",
        ],
        stderr=subprocess.DEVNULL,
    )

    print("🧟 Purging orphaned VLLM/EngineCore processes...")
    subprocess.run(["pkill", "-9", "-f", "VLLM|sparkrun|vllm"], stderr=subprocess.DEVNULL)

    # Launch backends
    print("🚀 Launching model instances via sparkrun...")
    global_network = stack.get("globals", {}).get("network", "proxy-tier")

    for backend in stack.get("backends", []):
        recipe_path = repo_root / "spark-stack-registry" / backend["recipe"]
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
            "--container-name",
            backend["name"],
            "--no-follow",
            "-o",
            f"network={global_network}",
        ]

        if "memory_limit" in backend:
            cmd.extend(["--memory-limit", backend["memory_limit"]])

        # Append overrides
        for key, value in backend.get("overrides", {}).items():
            cmd.extend(["-o", f"{key}={value}"])

        # Append environment variables
        for key, value in backend.get("env", {}).items():
            cmd.extend(["-o", f"env.{key}={value}"])

        # Append labels
        for label in backend.get("labels", []):
            cmd.extend(["--label", label])

        run_command(cmd, cwd=repo_root)

    # Launch compose services
    print("📦 Starting gateway and monitoring via docker compose...")
    compose_file = stack.get("services", {}).get("compose_file", "docker-compose.yaml")
    run_command(
        [
            "docker",
            "compose",
            "--env-file",
            str(parent_env),
            "-f",
            str(stack_dir / compose_file),
            "up",
            "-d",
        ],
        cwd=stack_dir,
    )
    print("✅ Stack is operational.")


if __name__ == "__main__":
    main()
