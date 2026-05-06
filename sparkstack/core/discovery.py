"""
vLLM and Sparkrun specific container discovery.
"""

from loguru import logger

from sparkstack.core.utils import async_run_command


async def get_container_name_by_port(port: int) -> str | None:
    """Find a container name that is publishing or listening on a specific port."""
    try:
        # 1. Check for docker containers publishing this port normally
        result = await async_run_command(
            ["docker", "ps", "--format", "{{.Names}}|{{.Ports}}"], check=False
        )
        for line in result.stdout.splitlines():
            if not line:
                continue
            name, ports = line.split("|")
            if f":{port}->" in ports or f":{port}" in ports:
                return name

        # 2. Check for sparkrun/host-network containers (using OR filter)
        result = await async_run_command(
            [
                "docker",
                "ps",
                "-f",
                "name=sparkrun",
                "-f",
                "name=solo",
                "-f",
                "name=main",
                "-f",
                "name=embedding",
                "--format",
                "{{.Names}}",
            ],
            check=False,
        )
        for container in result.stdout.splitlines():
            if not container:
                continue
            # 1. Check process list
            ps_res = await async_run_command(
                ["docker", "exec", container, "ps", "aux"], check=False
            )
            if f"--port {port}" in ps_res.stdout or f"--port={port}" in ps_res.stdout:
                return container

            # 2. Check the launch script (sparkrun specific)
            script_res = await async_run_command(
                ["docker", "exec", container, "cat", "/tmp/sparkrun_serve.sh"], check=False
            )
            if f"--port {port}" in script_res.stdout or f"--port={port}" in script_res.stdout:
                return container
    except Exception:
        logger.exception(f"Error resolving container for port {port}")

    return None
