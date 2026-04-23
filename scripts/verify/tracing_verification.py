import httpx
import asyncio
from loguru import logger
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 7: Tracing Verification")
async def run(ctx: VerifyContext):
    """
    Ensure Tempo is reachable and actively receiving traces from OpenClaw via OTLP.
    """
    max_retries = 12
    tempo_search_url = "http://127.0.0.1:3200/api/search"

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            try:
                openclaw_res = await client.get(
                    tempo_search_url, params={"tags": "service.name=openclaw-gateway"}, timeout=10
                )
                litellm_res = await client.get(
                    tempo_search_url, params={"tags": "service.name=litellm"}, timeout=10
                )
                vllm_res = await client.get(
                    tempo_search_url, params={"tags": "service.name=vllm-main"}, timeout=10
                )
                if openclaw_res.status_code == 200 and litellm_res.status_code == 200 and vllm_res.status_code == 200:
                    openclaw_data = openclaw_res.json()
                    litellm_data = litellm_res.json()
                    vllm_data = vllm_res.json()
                    openclaw_traces = openclaw_data.get("traces", [])
                    litellm_traces = litellm_data.get("traces", [])
                    vllm_traces = vllm_data.get("traces", [])

                    if len(openclaw_traces) > 0 and len(litellm_traces) > 0 and len(vllm_traces) > 0:
                        logger.info(
                            f"✅ Pass: Tracing Verification ({len(openclaw_traces)} OpenClaw, {len(litellm_traces)} LiteLLM, {len(vllm_traces)} vLLM traces found in Tempo)"
                        )
                        return True
                    else:
                        if attempt < max_retries - 1:
                            logger.debug("Waiting for traces to flush to Tempo...")
                            await asyncio.sleep(5)
                            continue
                        else:
                            logger.error(
                                f"❌ Failure: Tempo is running, but traces are missing. OpenClaw: {len(openclaw_traces)}, LiteLLM: {len(litellm_traces)}, vLLM: {len(vllm_traces)}."
                            )
                            return False
                else:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)
                        continue
                    else:
                        logger.error(
                            f"❌ Failure: Tempo API returned HTTP errors. OpenClaw: {openclaw_res.status_code}, LiteLLM: {litellm_res.status_code}"
                        )
                        return False
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                else:
                    logger.error(f"❌ Failure: Error querying Tempo: {e}")
                    return False
