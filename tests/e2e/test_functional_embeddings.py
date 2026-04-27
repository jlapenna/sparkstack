import os

import httpx
import pytest
from dotenv import load_dotenv
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(8)
@pytest.mark.asyncio
async def test_functional_embeddings(ctx: E2EContext):
    load_dotenv(ctx.root_dir / ".env")
    api_key = os.getenv("LITELLM_MASTER_KEY", "")

    if not api_key:
        logger.error("❌ LITELLM_MASTER_KEY not found in .env")
        raise AssertionError()

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {"input": "test", "model": "embedding"}

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{ctx.gateway_url}/embeddings", headers=headers, json=payload, timeout=30
        )
        if res.status_code == 200:
            data = res.json()
            if data.get("object") == "list" and "data" in data and len(data["data"]) > 0:
                dim = len(data["data"][0].get("embedding", []))
                logger.info(f"✅ Pass: Embedding endpoint reachable (dimension: {dim})")
                return
            else:
                logger.error("❌ Failure: Invalid embedding structure")
                raise AssertionError()
        else:
            logger.error(f"❌ Failure: Embeddings returned {res.status_code}: {res.text}")
            raise AssertionError()
