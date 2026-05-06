import os

import httpx
import pytest
from dotenv import load_dotenv
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(6)
@pytest.mark.asyncio
async def test_proxy_integrity(ctx: E2EContext):
    load_dotenv(ctx.root_dir / ".env")
    api_key = os.getenv("LITELLM_MASTER_KEY", "")

    if not api_key:
        logger.error("❌ LITELLM_MASTER_KEY not found in .env")
        raise AssertionError()

    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{ctx.gateway_url}/models", headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            models = [m["id"] for m in data.get("data", [])]
            logger.info(f"Routed Models: {', '.join(models)}")
            if "main" in models and "embedding" in models:
                logger.info("✅ Pass: Proxy Integrity")
                return
            logger.error(f"❌ Failure: Expected 'main' and 'embedding', got {models}")
            raise AssertionError()
        logger.error(f"❌ Failure: Gateway returned {res.status_code}")
        raise AssertionError()


@pytest.mark.order(7)
@pytest.mark.asyncio
async def test_litellm_config_no_host_docker_internal(ctx: E2EContext):
    config_path = ctx.stack_dir / "litellm-config.yaml"
    if config_path.exists():
        content = config_path.read_text()
        if "host.docker.internal" in content:
            logger.error("❌ Failure: host.docker.internal found in litellm-config.yaml")
            raise AssertionError()
        logger.info("✅ Pass: litellm-config.yaml does not use host.docker.internal")
    else:
        logger.warning(f"⚠️ Skip: litellm-config.yaml not found at {config_path}")
