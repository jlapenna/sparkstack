"""
Remote infrastructure module for managing multi-node deployments.

Handles Tailscale sidecar deployment (Docker container approach),
SSH execution, Tailnet IP resolution, and sidecar state persistence.

Architecture: One Tailscale sidecar container per remote host. All backend
containers on that host join the sidecar's network namespace via
``network_mode: container:sparkstack-sidecar-{hostname}``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sparkstack.core.env import SPARKSTACK_TAILSCALE_VERSION, get_headscale_url

logger = logging.getLogger(__name__)

# Container name prefix for all Tailscale sidecar containers.
_SIDECAR_PREFIX = "sparkstack-sidecar"

# Head sidecar container name (local, on the head node).
HEAD_SIDECAR_NAME = "sparkstack-head-sidecar"

# Headscale admin container name.
HEADSCALE_CONTAINER = "sparkstack-headscale"


def sidecar_name(hostname: str) -> str:
    """Return the Tailscale sidecar container name for a given remote hostname."""
    return f"{_SIDECAR_PREFIX}-{hostname}"


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------


async def run_ssh_command(target: str, command: str, timeout: int = 60) -> str:
    """Run a command over SSH and return stdout.

    Args:
        target: SSH target, e.g. ``"user@spark"`` or ``"spark"``.
        command: Shell command to execute remotely.
        timeout: Maximum seconds to wait.

    Raises:
        TimeoutError: If the command exceeds *timeout* seconds.
        RuntimeError: If the remote command exits non-zero.
    """
    cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        target,
        command,
    ]
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
        raise TimeoutError(f"SSH command timed out after {timeout}s on {target}: {command}") from e

    if process.returncode != 0:
        err_msg = stderr.decode().strip()
        raise RuntimeError(f"SSH command failed on {target} (exit {process.returncode}): {err_msg}")

    return stdout.decode().strip()


# ---------------------------------------------------------------------------
# Headscale helpers
# ---------------------------------------------------------------------------


async def get_headscale_auth_key(user: str = "sparkstack") -> str:
    """Generate a reusable pre-auth key from the local Headscale container.

    Uses Headscale v0.28 CLI syntax.  The ``sparkstack-headscale`` container
    must be running and healthy before this is called.

    Args:
        user: Headscale user/namespace to generate the key for.

    Returns:
        The raw pre-auth key string.

    Raises:
        RuntimeError: If key generation fails.
    """
    # Idempotent user creation — ignore error if user already exists.
    user_cmd = [
        "docker",
        "exec",
        HEADSCALE_CONTAINER,
        "headscale",
        "users",
        "create",
        user,
    ]
    proc = await asyncio.create_subprocess_exec(
        *user_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()  # Intentionally ignore exit code.

    # Resolve user ID by parsing the users list.
    user_id = None
    list_cmd = [
        "docker",
        "exec",
        HEADSCALE_CONTAINER,
        "headscale",
        "users",
        "list",
        "--output",
        "json",
    ]
    proc = await asyncio.create_subprocess_exec(
        *list_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode == 0:
        try:
            users_list = json.loads(stdout.decode())
            for u in users_list:
                if u.get("name") == user:
                    user_id = str(u.get("id"))
                    break
        except Exception as e:
            logger.warning("Failed to parse headscale users list JSON: %s", e)

    if not user_id:
        logger.warning("Could not resolve user ID for user '%s', falling back to '1'", user)
        user_id = "1"

    # Generate a reusable 10-year key (87600h).
    key_cmd = [
        "docker",
        "exec",
        HEADSCALE_CONTAINER,
        "headscale",
        "preauthkeys",
        "create",
        "--user",
        user_id,
        "--reusable",
        "--expiration",
        "87600h",
    ]
    proc = await asyncio.create_subprocess_exec(
        *key_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to generate Headscale auth key: {stderr.decode().strip()}")

    # v0.28 outputs the key as the last (or only) non-empty line of stdout.
    output = stdout.decode().strip()
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line:
            return line

    raise RuntimeError(f"Empty output from headscale preauthkeys create: {output!r}")


# ---------------------------------------------------------------------------
# Head sidecar (local, on the head node)
# ---------------------------------------------------------------------------


async def deploy_head_sidecar(
    network: str = "sparkstack-net",
    secondary_network: str = "vllm-network",
    sidecar_timeout: int = 60,
) -> None:
    """Deploy the head-node Tailscale sidecar if not already running.

    The sidecar uses the official ``tailscale/tailscale`` image and
    authenticates to the local Headscale control plane via ``TS_AUTHKEY``.
    It exposes LiteLLM, OTLP, and Prometheus ports so that local tools
    (``curl``, smoke tests, ``sparkstack wait``) can reach them at
    ``localhost:{port}`` without routing through Docker DNS.

    Args:
        network: Primary Docker bridge network to attach the sidecar to.
        secondary_network: Additional network to attach (for LiteLLM / vLLM
            traffic originating on ``vllm-network``).
        sidecar_timeout: Seconds to wait for the Tailnet connection.

    Raises:
        ValueError: If Headscale URL or auth key are not configured.
        RuntimeError: If the sidecar fails to start or connect.
    """
    from sparkstack.core.env import SPARKSTACK_HEADSCALE_AUTH_KEY  # noqa: PLC0415

    headscale_url = get_headscale_url()
    if not headscale_url:
        raise ValueError(
            "Headscale URL is not configured. Set SPARKSTACK_HEADSCALE_SERVER in .env."
        )

    auth_key = SPARKSTACK_HEADSCALE_AUTH_KEY
    if not auth_key:
        raise ValueError(
            "SPARKSTACK_HEADSCALE_AUTH_KEY is not set. Run 'sparkstack setup overlay' first."
        )

    # Idempotency: if the sidecar is already running and healthy, skip.
    if await _is_sidecar_healthy_local(HEAD_SIDECAR_NAME):
        logger.info("Head sidecar '%s' is already running and healthy.", HEAD_SIDECAR_NAME)
        return

    # Remove any unhealthy/stopped sidecar before recreating.
    await _remove_container_if_exists_local(HEAD_SIDECAR_NAME)

    ts_version = SPARKSTACK_TAILSCALE_VERSION
    logger.info("Deploying head sidecar (image: tailscale/tailscale:%s)...", ts_version)

    import os  # noqa: PLC0415
    from sparkstack.core.env import MONITORING_NODE_TARGET  # noqa: PLC0415

    enabled_services_str = os.getenv("SPARKSTACK_ENABLED_SERVICES")
    if enabled_services_str is not None:
        enabled_services = [s.strip().lower() for s in enabled_services_str.split(",") if s.strip()]
        has_monitoring = "monitoring" in enabled_services
    else:
        has_monitoring = True

    is_monitoring_local = (
        not MONITORING_NODE_TARGET
        or "localhost" in MONITORING_NODE_TARGET
        or "127.0.0.1" in MONITORING_NODE_TARGET
    )
    local_monitoring_enabled = has_monitoring and is_monitoring_local

    port_args = [
        "-p",
        "4000:4000",  # LiteLLM
    ]
    if not local_monitoring_enabled:
        port_args.extend([
            "-p", "4318:4318",  # OTLP HTTP
            "-p", "9090:9090",  # Prometheus
        ])

    run_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        HEAD_SIDECAR_NAME,
        "--cap-add",
        "NET_ADMIN",
        "--cap-add",
        "NET_RAW",
        "--device",
        "/dev/net/tun:/dev/net/tun",
        "--network",
        network,
        "--restart",
        "unless-stopped",
    ] + port_args + [
        "-v",
        "sparkstack-ts-state-head:/var/lib/tailscale",
        "-e",
        f"TS_AUTHKEY={auth_key}",
        "-e",
        "TS_STATE_DIR=/var/lib/tailscale",
        "-e",
        "TS_ACCEPT_DNS=false",
        "-e",
        f"TS_EXTRA_ARGS=--login-server={headscale_url}",
        "-e",
        "TS_HOSTNAME=sparkstack-head",
        f"tailscale/tailscale:{ts_version}",
    ]

    proc = await asyncio.create_subprocess_exec(
        *run_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start head sidecar: {stderr.decode().strip()}")

    # Attach to the secondary network so services on vllm-network can route out.
    attach_cmd = ["docker", "network", "connect", secondary_network, HEAD_SIDECAR_NAME]
    proc = await asyncio.create_subprocess_exec(
        *attach_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    # Non-fatal — the network may already be connected.
    if proc.returncode != 0:
        logger.debug(
            "network connect %s → %s: %s",
            secondary_network,
            HEAD_SIDECAR_NAME,
            stderr.decode().strip(),
        )

    # Wait for the sidecar to join the Tailnet.
    logger.info("Waiting for head sidecar to connect to Tailnet (timeout: %ds)...", sidecar_timeout)
    await _wait_for_sidecar_local(HEAD_SIDECAR_NAME, timeout=sidecar_timeout)
    logger.info("✅ Head sidecar is connected to the Tailnet.")


async def resolve_head_tailnet_ip() -> str:
    """Return the head sidecar's own Tailnet IP (100.x.y.z).

    Raises:
        RuntimeError: If the IP cannot be resolved.
    """
    return await _get_sidecar_ip_local(HEAD_SIDECAR_NAME)


# ---------------------------------------------------------------------------
# Worker sidecars (remote, one per host)
# ---------------------------------------------------------------------------


async def deploy_worker_sidecar(
    target: str,
    hostname: str,
    auth_key: str,
    headscale_url: str,
    *,
    sidecar_timeout: int = 60,
) -> None:
    """Deploy a Tailscale sidecar container on a remote worker via SSH.

    Uses the per-host naming scheme: one sidecar per host regardless of how
    many backend roles are deployed to that host.  All backend containers on
    the host share the sidecar's network namespace.

    Args:
        target: SSH target string, e.g. ``"user@spark"`` or ``"spark"``.
        hostname: Short hostname used in container/volume naming (e.g. ``"spark"``).
        auth_key: Headscale pre-auth key.
        headscale_url: Routable URL for the Headscale control plane.
        sidecar_timeout: Seconds to wait for the Tailnet connection.

    Raises:
        RuntimeError: If the sidecar fails to deploy or connect.
    """
    name = sidecar_name(hostname)
    ts_version = SPARKSTACK_TAILSCALE_VERSION
    ts_hostname = f"sparkstack-worker-{hostname}"

    logger.info("Deploying worker sidecar '%s' on %s...", name, target)

    # Idempotency: skip if already running and healthy.
    try:
        if await _is_sidecar_healthy_remote(target, name):
            logger.info("Worker sidecar '%s' is already running and healthy.", name)
            return
    except Exception as e:
        logger.debug("Health check skipped for '%s': %s", name, e)

    # Remove any unhealthy/stopped sidecar.
    try:
        await run_ssh_command(
            target,
            f"docker rm -f {name} 2>/dev/null || true",
        )
    except Exception as e:
        logger.debug("Pre-cleanup for '%s' failed (non-fatal): %s", name, e)

    docker_run = (
        f"docker run -d"
        f" --name {name}"
        f" --cap-add NET_ADMIN"
        f" --cap-add NET_RAW"
        f" --device /dev/net/tun:/dev/net/tun"
        f" --restart unless-stopped"
        f" -v sparkstack-ts-state-{hostname}:/var/lib/tailscale"
        f" -e TS_AUTHKEY={auth_key}"
        f" -e TS_STATE_DIR=/var/lib/tailscale"
        f" -e TS_ACCEPT_DNS=false"
        f" -e 'TS_EXTRA_ARGS=--login-server={headscale_url}'"
        f" -e TS_HOSTNAME={ts_hostname}"
        f" tailscale/tailscale:{ts_version}"
    )

    await run_ssh_command(target, docker_run, timeout=30)
    logger.info("Worker sidecar started on %s. Waiting for Tailnet connection...", target)

    # Poll for Tailnet connectivity.
    deadline = asyncio.get_event_loop().time() + sidecar_timeout
    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise RuntimeError(
                f"Worker sidecar '{name}' on {target} did not connect to "
                f"the Tailnet within {sidecar_timeout}s."
            )
        try:
            healthy = await _is_sidecar_healthy_remote(target, name)
            if healthy:
                logger.info("✅ Worker sidecar '%s' on %s is connected.", name, target)
                return
        except Exception as e:
            logger.debug("Health poll for '%s': %s", name, e)
        await asyncio.sleep(3)


async def resolve_worker_tailnet_ip(target: str, hostname: str) -> str:
    """Return the Tailnet IP of a worker sidecar by querying it via SSH.

    Args:
        target: SSH target for the remote host.
        hostname: Short hostname, used to derive the container name.

    Returns:
        Tailnet IP string, e.g. ``"100.64.0.2"``.

    Raises:
        RuntimeError: If the IP cannot be resolved.
    """
    name = sidecar_name(hostname)
    ip = await run_ssh_command(
        target,
        f"docker exec {name} tailscale ip -4",
        timeout=15,
    )
    ip = ip.strip()
    if not ip:
        raise RuntimeError(f"Empty Tailnet IP from sidecar '{name}' on {target}")
    return ip


async def poll_sidecar_health(target: str, hostname: str) -> bool:
    """Check if a remote worker sidecar is healthy and connected to the Tailnet.

    Args:
        target: SSH target for the remote host.
        hostname: Short hostname (used to derive the container name).

    Returns:
        ``True`` if the sidecar is running and BackendState is "Running".
    """
    try:
        name = sidecar_name(hostname)
        return await _is_sidecar_healthy_remote(target, name)
    except Exception as e:
        logger.warning("Health check failed for sidecar on %s: %s", target, e)
        return False


# ---------------------------------------------------------------------------
# Sidecar state (.state.json)
# ---------------------------------------------------------------------------

_STATE_FILE = ".state.json"


def write_sidecar_state(
    stack_dir: Path,
    cluster_name: str,
    sidecars: dict[str, dict[str, str]],
) -> None:
    """Persist sidecar metadata to ``{stack_dir}/.state.json``.

    This file tracks only Tailscale infrastructure that sparkrun has no
    concept of.  It is **not** a full deployment manifest.

    Args:
        stack_dir: Path to the active stack directory.
        cluster_name: sparkrun cluster name used for teardown resolution.
        sidecars: Mapping of ``{hostname: {container_name, tailnet_ip, role}}``.
            Example::

                {
                    "spark": {
                        "container_name": "sparkstack-sidecar-spark",
                        "tailnet_ip": "100.64.0.2",
                        "role": "worker",
                    }
                }
    """
    state: dict[str, Any] = {
        "deployed_at": datetime.now(UTC).isoformat(),
        "cluster_name": cluster_name,
        "sidecars": sidecars,
    }
    state_path = stack_dir / _STATE_FILE
    state_path.write_text(json.dumps(state, indent=2))
    logger.debug("Sidecar state written to %s", state_path)


def read_sidecar_state(stack_dir: Path) -> dict[str, Any]:
    """Read ``{stack_dir}/.state.json``.

    Returns an empty dict if the file does not exist or cannot be parsed.
    """
    state_path = stack_dir / _STATE_FILE
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text())
    except Exception as e:
        logger.warning("Could not read sidecar state from %s: %s", state_path, e)
        return {}


async def teardown_sidecars(
    stack_dir: Path,
    hosts_to_keep: set[str],
    ssh_user: str = "",
) -> None:
    """Remove sidecar containers on hosts no longer in the new deployment.

    This is Tier 2 of the two-tier orphan teardown.  Must be called *after*
    Tier 1 (``sparkrun stop --all``).

    Args:
        stack_dir: Path to the outgoing stack directory (where ``.state.json`` lives).
        hosts_to_keep: Hostnames of hosts that should keep their sidecars.
        ssh_user: Optional SSH username prefix (e.g. ``"user@"``). If set,
            the SSH target becomes ``"{ssh_user}{hostname}"``.
    """
    state = read_sidecar_state(stack_dir)
    sidecars = state.get("sidecars", {})
    if not sidecars:
        return

    updated_sidecars = dict(sidecars)
    for hostname, info in sidecars.items():
        if hostname in hosts_to_keep:
            continue

        container = info.get("container_name", sidecar_name(hostname))
        target = f"{ssh_user}{hostname}" if ssh_user else hostname

        logger.info("Removing sidecar '%s' from %s...", container, target)
        try:
            await run_ssh_command(
                target,
                f"docker rm -f {container} 2>/dev/null || true",
                timeout=15,
            )
            logger.info("  ✅ Sidecar '%s' removed.", container)
        except Exception as e:
            logger.warning("  ⚠️  Failed to remove sidecar '%s' on %s: %s", container, target, e)

        updated_sidecars.pop(hostname, None)

    # Persist the updated state.
    if updated_sidecars != sidecars:
        state["sidecars"] = updated_sidecars
        state_path = stack_dir / _STATE_FILE
        state_path.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _is_sidecar_healthy_local(container_name: str) -> bool:
    """Return True if the named local container is running and Tailnet-connected."""
    # 1. Is it running?
    check_cmd = ["docker", "ps", "-q", "-f", f"name=^{container_name}$"]
    proc = await asyncio.create_subprocess_exec(
        *check_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if not stdout.strip():
        return False

    # 2. Is it Tailnet-connected?
    try:
        status_cmd = [
            "docker",
            "exec",
            container_name,
            "tailscale",
            "status",
            "--json",
        ]
        proc = await asyncio.create_subprocess_exec(
            *status_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        data = json.loads(stdout.decode())
        return data.get("BackendState") == "Running"
    except Exception:
        return False


async def _is_sidecar_healthy_remote(target: str, container_name: str) -> bool:
    """Return True if the named remote container is running and Tailnet-connected."""
    try:
        output = await run_ssh_command(
            target,
            f"docker exec {container_name} tailscale status --json 2>/dev/null || echo '{{}}'",
            timeout=15,
        )
        data = json.loads(output)
        return data.get("BackendState") == "Running"
    except Exception:
        return False


async def _remove_container_if_exists_local(container_name: str) -> None:
    """Remove a local container if it exists (running or stopped)."""
    rm_cmd = ["docker", "rm", "-f", container_name]
    proc = await asyncio.create_subprocess_exec(
        *rm_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()  # Ignore exit code — container may not exist.


async def _wait_for_sidecar_local(container_name: str, timeout: int = 60) -> None:
    """Poll a local sidecar until it connects to the Tailnet or timeout expires."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        if asyncio.get_event_loop().time() > deadline:
            raise RuntimeError(
                f"Sidecar '{container_name}' did not connect to the Tailnet within {timeout}s."
            )
        if await _is_sidecar_healthy_local(container_name):
            return
        await asyncio.sleep(3)


async def _get_sidecar_ip_local(container_name: str) -> str:
    """Return the Tailnet IP of a local sidecar container."""
    ip_cmd = [
        "docker",
        "exec",
        container_name,
        "tailscale",
        "ip",
        "-4",
    ]
    proc = await asyncio.create_subprocess_exec(
        *ip_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to get Tailnet IP for '{container_name}': {stderr.decode().strip()}"
        )
    ip = stdout.decode().strip()
    if not ip:
        raise ValueError(f"Empty Tailnet IP for '{container_name}'")
    return ip
