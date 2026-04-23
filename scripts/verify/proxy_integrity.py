import httpx
from loguru import logger
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 2: Proxy Integrity (Routing)")
async def run(ctx: VerifyContext):
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{ctx.gateway_url}/models", timeout=10)
        if res.status_code == 200:
            data = res.json()
            models = [m["id"] for m in data.get("data", [])]
            logger.info(f"Routed Models: {', '.join(models)}")
            if "main" in models and "embedding" in models:
                logger.info("✅ Pass: Proxy Integrity")
                return True
            else:
                logger.error(f"❌ Failure: Expected 'main' and 'embedding', got {models}")
                return False
        else:
            logger.error(f"❌ Failure: Gateway returned {res.status_code}")
            return False
