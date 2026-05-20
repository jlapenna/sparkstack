import os

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(5)
@pytest.mark.asyncio
async def test_cloudflare(ctx: E2EContext):
    enabled_services = os.environ.get("SPARKSTACK_ENABLED_SERVICES", "")
    enabled_keys = {s.strip().lower() for s in enabled_services.split(",") if s.strip()}
    if "cloudflare" not in enabled_keys:
        pytest.skip("Cloudflare service is disabled in SPARKSTACK_ENABLED_SERVICES")

    logger.info("Checking Cloudflare tunnel container status...")

    # 1. Check if container is running
    ps_cmd = ["docker", "ps", "--format", "{{.Names}}"]
    res_ps = await async_run_command(ps_cmd, check=False)

    if "cloudflared" not in res_ps.stdout:
        logger.error("❌ Failure: Cloudflare tunnel container ('cloudflared') is not running.")
        raise AssertionError()

    # 2. Inspect for TUNNEL_TOKEN
    inspect_cmd = [
        "docker",
        "inspect",
        "cloudflared",
        "--format",
        "{{range .Config.Env}}{{println .}}{{end}}",
    ]
    res_inspect = await async_run_command(inspect_cmd, check=False)

    envs = res_inspect.stdout.splitlines()
    token = next((e.split("=", 1)[1] for e in envs if e.startswith("TUNNEL_TOKEN=")), "")

    if not token:
        logger.error("❌ Failure: cloudflared is running but TUNNEL_TOKEN is empty or missing.")
        raise AssertionError()

    logger.info("✅ Pass: Cloudflare tunnel is running with a valid TUNNEL_TOKEN.")
    return
