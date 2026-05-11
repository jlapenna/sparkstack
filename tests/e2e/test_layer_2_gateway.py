import pytest
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(5)
@pytest.mark.asyncio
async def test_layer_2_gateway_inference(ctx: E2EContext):
    async with ctx.gateway_client() as client:
        res_models = await client.get("/models", timeout=10)
        if res_models.status_code != 200:
            logger.error(f"❌ Failure: Gateway returned {res_models.status_code} for /models")
            raise AssertionError("Gateway models endpoint failed")

        data = res_models.json()
        models = [m["id"] for m in data.get("data", [])]
        logger.info(f"Routed Models: {', '.join(models)}")

        if "main" not in models or "embedding" not in models:
            logger.error(f"❌ Failure: Expected 'main' and 'embedding', got {models}")
            raise AssertionError("Missing required models on gateway")

        # Test routing via LiteLLM
        res = await client.post(
            "/chat/completions",
            json={
                "model": "main",
                "messages": [{"role": "user", "content": "Say hi"}],
                "max_tokens": 5,
            },
            timeout=180.0,
        )

        if res.status_code == 200:
            logger.info("✅ Pass: Layer 2 Gateway Inference")
            return

        logger.error(f"❌ Failure: Gateway inference failed: {res.status_code} - {res.text}")
        raise AssertionError("Gateway inference failed")


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
