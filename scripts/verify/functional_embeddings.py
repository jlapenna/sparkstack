import os
import httpx
from dotenv import load_dotenv
from loguru import logger
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 3: Functional Verification (Embeddings)")
async def run(ctx: VerifyContext):
    load_dotenv(ctx.root_dir / ".env")
    api_key = os.getenv("VLLM_SPARK_API_KEY", "")

    if not api_key:
        logger.error("❌ VLLM_SPARK_API_KEY not found in .env")
        return False

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
                return True
            else:
                logger.error("❌ Failure: Invalid embedding structure")
                return False
        else:
            logger.error(f"❌ Failure: Embeddings returned {res.status_code}: {res.text}")
            return False
