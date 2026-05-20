import sys

from loguru import logger

from sparkstack.core.env import OPENCLAW_CONFIG_DIR
from sparkstack.core.utils import async_run_command


async def _check_remote_node(target: str, label: str) -> None:
    """Verify SSH reachability of a remote node target.

    Strips protocol prefixes (``ssh://``) so the target is a bare
    ``user@host`` suitable for an SSH connectivity test.
    """
    from sparkstack.manager.remote import run_ssh_command  # noqa: PLC0415

    ssh_target = target.replace("ssh://", "")
    logger.info(f"Verifying SSH connectivity to {label} ({ssh_target})...")
    try:
        await run_ssh_command(ssh_target, "echo ok", timeout=15)
        logger.info(f"  ✅ {label} ({ssh_target}) is reachable via SSH.")
    except Exception as e:
        logger.error(
            f"  ❌ {label} ({ssh_target}) is unreachable via SSH: {e}\n"
            f"     Ensure the node is online, SSH is configured for key-based "
            f"auth (BatchMode=yes), and the target is correct."
        )
        sys.exit(1)


async def _check_sidecar_health(target: str, label: str) -> None:
    """Verify a remote Tailscale sidecar is authenticated and running."""
    from sparkstack.manager.remote import poll_sidecar_health  # noqa: PLC0415

    ssh_target = target.replace("ssh://", "")
    hostname = ssh_target.split("@")[-1]
    logger.info(f"Verifying Tailscale sidecar on {label} ({ssh_target})...")
    healthy = await poll_sidecar_health(ssh_target, hostname)
    if healthy:
        logger.info(f"  ✅ Tailscale sidecar on {label} is healthy.")
    else:
        logger.warning(
            f"  ⚠️ Tailscale sidecar on {label} is not healthy or not running. "
            f"It will be deployed/reconnected during the HeadscaleService phase."
        )


async def pre_flight_checks(settings):
    logger.info("Checking system readiness...")

    # Check .env
    env_path = settings.project_root / ".env"
    if not env_path.exists():
        logger.error(f"Missing .env file at {env_path}")
        sys.exit(1)

    # Check Docker daemon
    try:
        await async_run_command(["docker", "info"], check=True, capture_output=True)
    except Exception:
        logger.error("Docker daemon is not running or accessible.")
        sys.exit(1)

    # Check/Create external network
    try:
        await async_run_command(
            ["docker", "network", "inspect", "sparkstack-net"], check=True, capture_output=True
        )
    except Exception:
        logger.info("Creating external network sparkstack-net")
        await async_run_command(["docker", "network", "create", "sparkstack-net"], check=True)

    # --- Remote node pre-flight checks ---
    from sparkstack.core.env import (  # noqa: PLC0415
        MONITORING_NODE_TARGET,
        OPENCLAW_NODE_TARGET,
        SPARK_NODE_TARGET,
        is_overlay_configured,
    )

    remote_targets = [
        (SPARK_NODE_TARGET, "Spark Worker"),
        (OPENCLAW_NODE_TARGET, "OpenClaw Node"),
        (MONITORING_NODE_TARGET, "Monitoring Node"),
    ]

    active_targets = [(t, label) for t, label in remote_targets if t]

    if active_targets:
        logger.info(f"Remote node targets detected ({len(active_targets)}). Validating...")
        for target, label in active_targets:
            await _check_remote_node(target, label)

        # If overlay is configured, also check sidecar health (non-fatal)
        if is_overlay_configured():
            for target, label in active_targets:
                await _check_sidecar_health(target, label)

    logger.info("Pre-flight complete.")


ZOMBIE_CONTAINER_PREFIXES = ("openclaw-sbx-", "openclaw-openclaw-cli-")


async def cleanup_zombies(settings=None):
    """The 'Zombie Protocol' - cleans up stuck tasks and stale containers."""
    logger.info("Executing Zombie Protocol...")

    # 1. Clear stuck OpenClaw tasks
    task_db = OPENCLAW_CONFIG_DIR / "tasks" / "runs.sqlite"
    if task_db.exists():
        logger.info(f"Clearing zombie tasks in {task_db}")
        try:
            await async_run_command(
                [
                    "sqlite3",
                    str(task_db),
                    "UPDATE task_runs SET status = 'failed', error = 'Zombie task cleared by update_services' WHERE status = 'running';",
                ],
                check=False,
            )
        except Exception as e:
            logger.warning(f"Failed to clear zombie tasks: {e}")

    # 2. Remove stale OpenClaw sandbox and CLI containers.
    # These are spawned dynamically by the gateway (not by Compose), so they
    # survive `docker compose up --force-recreate openclaw-gateway` indefinitely.
    # The gateway will recreate them on demand after the redeploy.
    logger.info("Removing stale OpenClaw sandbox and CLI containers...")
    for name_filter in ZOMBIE_CONTAINER_PREFIXES:
        try:
            result = await async_run_command(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"name={name_filter}",
                ],
                check=False,
                capture_output=True,
            )
            container_ids = result.stdout.strip().split() if result.stdout else []
            if container_ids:
                logger.info(f"Removing {len(container_ids)} containers matching '{name_filter}*'")
                await async_run_command(
                    ["docker", "rm", "-f", *container_ids],
                    check=False,
                )
        except Exception as e:
            logger.warning(f"Failed to remove containers matching '{name_filter}*': {e}")

    # 3. Cleanup stale containers (orphaned or exited long ago)
    logger.info("Cleaning up stale containers and networks...")
    try:
        # Restrict blast radius to ONLY our specific compose projects to prevent destroying unrelated host resources
        compose_projects = ["current", "monitoring", "openclaw", "cloudflare"]
        for proj in compose_projects:
            await async_run_command(
                [
                    "docker",
                    "container",
                    "prune",
                    "-f",
                    "--filter",
                    f"label=com.docker.compose.project={proj}",
                ],
                check=False,
            )

            await async_run_command(
                [
                    "docker",
                    "network",
                    "prune",
                    "-f",
                    "--filter",
                    f"label=com.docker.compose.project={proj}",
                ],
                check=False,
            )
    except Exception as e:
        logger.warning(f"Docker cleanup failed: {e}")

    # 4. Flush stale telemetry caches
    logger.info("Flushing telemetry cache (restarting alloy)...")
    try:
        await async_run_command(["docker", "restart", "alloy"], check=False)
    except Exception as e:
        logger.warning(f"Failed to restart alloy: {e}")
