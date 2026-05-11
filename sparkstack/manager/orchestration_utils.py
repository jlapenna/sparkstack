import sys

from loguru import logger

from sparkstack.core.env import OPENCLAW_CONFIG_DIR
from sparkstack.core.utils import async_run_command


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
