import os
import time
import uuid
import asyncio
import httpx
from dotenv import load_dotenv
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 7: Reliability Soak Test")
async def run(ctx: VerifyContext, minutes: int = 2):
    print(f"Beginning {minutes}-minute soak. Polling every 15s...")
    load_dotenv(ctx.root_dir / ".env")
    api_key = os.getenv("VLLM_SPARK_API_KEY", "")
    if not api_key:
        print("❌ VLLM_SPARK_API_KEY not found in .env")
        return False

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    interval = 15
    samples = (minutes * 60) // interval
    async with httpx.AsyncClient() as client:
        for i in range(samples):
            start_time = time.time()
            payload = {
                "input": f"reliability soak test unique payload {uuid.uuid4()}",
                "model": "embedding",
            }
            res = await client.post(
                f"{ctx.gateway_url}/embeddings", headers=headers, json=payload, timeout=30
            )
            if res.status_code != 200:
                print(f"❌ Failure: Probe {i + 1} failed with {res.status_code}: {res.text}")
                return False

            elapsed = time.time() - start_time
            wait_time = max(0.0, interval - elapsed)
            print(f"Probe {i + 1}/{samples}: OK ({elapsed:.2f}s). Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)

    print(f"✅ Pass: Reliability Soak ({minutes} minutes stable)")
    return True
