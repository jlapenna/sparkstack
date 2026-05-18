"""
Remote infrastructure module for managing multi-node deployments.
Handles sidecar deployment, SSH execution, and IP resolution.
"""

import asyncio
import json
import logging

from sparkstack.core.env import get_headscale_url

logger = logging.getLogger(__name__)


async def run_ssh_command(target: str, command: str, timeout: int = 60) -> str:
    """Run a command over SSH."""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", target, command]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as e:
        process.kill()
        await process.wait()
        raise TimeoutError(f"SSH command timed out after {timeout}s: {command}") from e

    if process.returncode != 0:
        err_msg = stderr.decode().strip()
        raise RuntimeError(f"SSH command failed on {target} (code {process.returncode}): {err_msg}")

    return stdout.decode().strip()


async def get_headscale_auth_key(user: str = "sparkstack") -> str:
    """Generate a pre-auth key from Headscale."""
    # 1. Create user if not exists
    user_cmd = ["docker", "exec", "headscale", "headscale", "users", "create", user]
    proc = await asyncio.create_subprocess_exec(*user_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await proc.communicate() # Ignore error if exists

    # 2. Generate key
    key_cmd = [
        "docker", "exec", "headscale",
        "headscale", "preauthkeys", "create", "-e", "24h", "-u", user, "--output", "json"
    ]
    proc = await asyncio.create_subprocess_exec(*key_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to generate headscale auth key: {stderr.decode().strip()}")

    try:
        data = json.loads(stdout)
        return data["key"]
    except Exception:
        # Fallback if json parsing fails
        lines = stdout.decode().strip().split("\n")
        return lines[-1].strip()


async def resolve_tailnet_ip(hostname: str) -> str:
    """Resolve a hostname to its Tailnet IP using the head sidecar."""
    cmd = ["docker", "exec", "sparkstack-head-sidecar", "tailscale", "ip", "-4", hostname]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"Failed to resolve Tailnet IP for {hostname}: {stderr.decode().strip()}")

    ip = stdout.decode().strip()
    if not ip:
        raise ValueError(f"Empty Tailnet IP resolved for {hostname}")
    return ip


async def deploy_head_sidecar(network: str = "sparkstack-net") -> None:
    """Deploy the local Tailscale sidecar connected to Headscale."""
    logger.info("Deploying head sidecar...")
    # Check if exists
    check_cmd = ["docker", "ps", "-q", "-f", "name=sparkstack-head-sidecar"]
    proc = await asyncio.create_subprocess_exec(*check_cmd, stdout=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()

    if stdout.strip():
        logger.info("Head sidecar is already running.")
        return

    headscale_url = get_headscale_url()
    if not headscale_url:
        raise ValueError("Headscale URL is not configured.")

    auth_key = await get_headscale_auth_key()

    run_cmd = [
        "docker", "run", "-d", "--name", "sparkstack-head-sidecar",
        "--network", network,
        "--cap-add=NET_ADMIN", "--cap-add=NET_RAW",
        "-v", "sparkstack-head-sidecar-data:/var/lib/tailscale",
        "tailscale/tailscale:latest"
    ]

    proc = await asyncio.create_subprocess_exec(*run_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start head sidecar: {stderr.decode().strip()}")

    # Wait for it to start
    await asyncio.sleep(2)

    # Connect it to headscale
    auth_cmd = [
        "docker", "exec", "sparkstack-head-sidecar",
        "tailscale", "up", "--login-server", headscale_url, "--authkey", auth_key, "--accept-routes"
    ]
    proc = await asyncio.create_subprocess_exec(*auth_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
         raise RuntimeError(f"Failed to authenticate head sidecar: {stderr.decode().strip()}")


async def deploy_worker_sidecar(target: str, auth_key: str, headscale_url: str) -> None:
    """Deploy Tailscale on a remote worker node via SSH."""
    logger.info(f"Deploying worker sidecar on {target}...")

    # Check if tailscaled is running
    try:
        await run_ssh_command(target, "systemctl is-active tailscaled")
        logger.info(f"Tailscale is already running on {target}.")
    except RuntimeError:
        # Install tailscale
        install_cmd = "curl -fsSL https://tailscale.com/install.sh | sh"
        await run_ssh_command(target, install_cmd, timeout=120)

    # Authenticate
    auth_cmd = f"sudo tailscale up --login-server {headscale_url} --authkey {auth_key} --accept-routes"
    await run_ssh_command(target, auth_cmd, timeout=30)
    logger.info(f"Worker sidecar deployed on {target}.")


async def poll_sidecar_health(target: str) -> bool:
    """Check if the sidecar on a remote node is healthy and connected to the tailnet."""
    try:
        stdout = await run_ssh_command(target, "sudo tailscale status --json", timeout=10)
        data = json.loads(stdout)

        # A simple check: BackendState should be "Running"
        return data.get("BackendState") == "Running"
    except Exception as e:
        logger.warning(f"Health check failed for sidecar on {target}: {e}")
        return False
