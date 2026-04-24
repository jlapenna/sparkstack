import subprocess
import time

import pytest
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.asyncio
async def test_system_health(ctx: E2EContext):
    # Check 1: Host zombie processes
    try:
        ps_out = subprocess.check_output(["ps", "-eo", "stat"], text=True)
        zombie_count = sum(1 for line in ps_out.splitlines() if line.startswith("Z"))
        if zombie_count > 10:
            logger.error(
                f"❌ Failure: Too many zombie processes on the host ({zombie_count}). Possible process leak."
            )
            raise AssertionError()
        else:
            logger.info(f"✅ Host zombie processes: {zombie_count} (acceptable)")
    except Exception as e:
        logger.error(f"❌ Failure: Could not check host processes: {e}")
        raise AssertionError() from None

    # Check 2: Docker daemon responsiveness
    try:
        start_time = time.time()
        subprocess.check_output(["docker", "info"], stderr=subprocess.STDOUT, timeout=5.0)
        elapsed = time.time() - start_time
        logger.info(f"✅ Docker daemon is responsive (responded in {elapsed:.2f}s)")
    except subprocess.TimeoutExpired:
        logger.error("❌ Failure: Docker daemon timed out (unresponsive). Possible deadlock.")
        raise AssertionError() from None
    except Exception as e:
        logger.error(f"❌ Failure: Docker daemon check failed: {e}")
        raise AssertionError() from None

    # Check 3: Check for unusual number of docker-exec processes
    try:
        ps_exec = subprocess.check_output(["pgrep", "-f", "docker exec"], text=True)
        exec_count = len([line for line in ps_exec.splitlines() if line.strip()])
    except subprocess.CalledProcessError:
        exec_count = 0  # no docker exec processes found

    if exec_count > 20:
        logger.error(
            f"❌ Failure: Detected {exec_count} concurrent 'docker exec' processes. Possible leak."
        )
        raise AssertionError() from None
    else:
        logger.info(f"✅ Concurrent 'docker exec' processes: {exec_count} (acceptable)")

    # Check 4: Check if any containers are in a Dead or restarting state
    try:
        docker_ps = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}: {{.State}}"], text=True
        )
        bad_containers = []
        for line in docker_ps.splitlines():
            if not line.strip():
                continue
            name, state = line.split(":", 1)
            state = state.strip().lower()
            if state in ["dead", "restarting"]:
                bad_containers.append((name, state))

        if bad_containers:
            logger.error(f"❌ Failure: Found containers in unexpected states: {bad_containers}")
            raise AssertionError() from None
        else:
            logger.info("✅ All containers are in expected states (running, created, or exited)")
    except Exception as e:
        logger.error(f"❌ Failure: Could not check container states: {e}")
        raise AssertionError() from None

    logger.info("✅ Pass: System & Container Health (No zombies or leaks detected)")
    return
