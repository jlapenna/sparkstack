import asyncio
import time
import uuid

import pytest

from tests.e2e.context import E2EContext


@pytest.mark.order(16)
@pytest.mark.timeout(1200)
@pytest.mark.asyncio
async def test_reliability(ctx: E2EContext):
    minutes = ctx.soak_minutes
    print(f"Beginning {minutes}-minute soak. Polling every 15s...")

    interval = 15
    samples = (minutes * 60) // interval
    async with ctx.gateway_client() as client:
        for i in range(samples):
            start_time = time.time()
            payload = {
                "input": f"reliability soak test unique payload {uuid.uuid4()}",
                "model": "embedding",
            }
            res = await client.post("/embeddings", json=payload, timeout=30)
            if res.status_code != 200:
                print(f"❌ Failure: Probe {i + 1} failed with {res.status_code}: {res.text}")
                raise AssertionError()

            elapsed = time.time() - start_time
            wait_time = max(0.0, interval - elapsed)
            print(f"Probe {i + 1}/{samples}: OK ({elapsed:.2f}s). Waiting {wait_time:.1f}s...")
            await asyncio.sleep(wait_time)

    print(f"✅ Pass: Reliability Soak ({minutes} minutes stable)")
    return
