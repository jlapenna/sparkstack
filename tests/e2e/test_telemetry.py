import asyncio

import httpx
import pytest
from loguru import logger

from tests.e2e.context import E2EContext


@pytest.mark.order(14)
@pytest.mark.asyncio
async def test_telemetry(ctx: E2EContext):
    max_retries = 6
    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                res = await client.get(ctx.telemetry_url, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    targets = [
                        t
                        for t in data.get("data", {}).get("activeTargets", [])
                        if t.get("labels", {}).get("job") == "vllm"
                    ]

                    all_up = True
                    for t in targets:
                        health = t.get("health", "unknown")
                        if health != "up":
                            all_up = False

                    if all_up and len(targets) > 0:
                        for t in targets:
                            model = t["labels"].get("model", "unknown")
                            health = t.get("health", "unknown")
                            logger.info(f"Target: {model} -> {health}")
                        logger.info("✅ Pass: Telemetry Verification")
                        return
                    else:
                        if attempt < max_retries - 1:
                            logger.debug("Waiting for telemetry targets to sync...")
                            await asyncio.sleep(5)
                            continue
                        else:
                            for t in targets:
                                model = t["labels"].get("model", "unknown")
                                health = t.get("health", "unknown")
                                logger.info(f"Target: {model} -> {health}")
                            logger.error("❌ Failure: Not all telemetry targets are 'up'")
                            raise AssertionError()
                else:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)
                        continue
                    else:
                        logger.error(f"❌ Failure: Prometheus returned HTTP {res.status_code}")
                        raise AssertionError()
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                else:
                    logger.error(f"❌ Failure: Error polling Prometheus: {e}")
                    raise AssertionError() from None
