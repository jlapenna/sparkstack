import httpx
import pytest
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(6)
@pytest.mark.asyncio
async def test_proxy_integrity(ctx: E2EContext):
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{ctx.gateway_url}/models", timeout=10)
        if res.status_code == 200:
            data = res.json()
            models = [m["id"] for m in data.get("data", [])]
            logger.info(f"Routed Models: {', '.join(models)}")
            if "main" in models and "embedding" in models:
                logger.info("✅ Pass: Proxy Integrity")
                return
            else:
                logger.error(f"❌ Failure: Expected 'main' and 'embedding', got {models}")
                raise AssertionError()
        else:
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
