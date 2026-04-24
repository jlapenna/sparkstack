import httpx
import pytest
from loguru import logger

from tests.e2e.context import E2EContext


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
