import pytest
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(8)
@pytest.mark.asyncio
async def test_functional_embeddings(ctx: E2EContext):
    async with ctx.gateway_client() as client:
        # Check if an embedding model is mapped before running the test
        models_res = await client.get("/models", timeout=10)
        if models_res.status_code == 200:
            models_data = models_res.json()
            available_models = [m.get("id") for m in models_data.get("data", [])]
            if "embedding" not in available_models:
                logger.info(
                    "⏭️ Skip: No 'embedding' model mapped in LiteLLM. Stack may have been built with --allow-no-embedding."
                )
                pytest.skip("No embedding model mapped.")

        payload = {"input": "test", "model": "embedding"}
        res = await client.post("/embeddings", json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            if data.get("object") == "list" and "data" in data and len(data["data"]) > 0:
                dim = len(data["data"][0].get("embedding", []))
                logger.info(f"✅ Pass: Embedding endpoint reachable (dimension: {dim})")
                return
            logger.error("❌ Failure: Invalid embedding structure")
            raise AssertionError()
        logger.error(f"❌ Failure: Embeddings returned {res.status_code}: {res.text}")
        raise AssertionError()
