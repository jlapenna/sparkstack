import asyncio

import httpx
import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(15)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_tracing(ctx: E2EContext):
    """
    Ensure Tempo is reachable and actively receiving traces from OpenClaw via OTLP,
    and that a complete trace spans across all required services.
    """
    logger.info("Triggering an agent inference to generate a trace...")
    inference_cmd = [
        str(ctx.openclaw_bin),
        "agent",
        "--agent",
        "verifier",
        "--message",
        "Tracing verification test. Please reply with OK.",
    ]
    try:
        # Timeout inference at 120s so a stalled backend doesn't eat the full test budget.
        result = await asyncio.wait_for(
            async_run_command(inference_cmd, check=False),
            timeout=120,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            logger.error(f"Inference exited with code {result.returncode}: {output[:500]}")
            raise AssertionError(f"Inference failed (rc={result.returncode}): {output[:500]}")
    except TimeoutError:
        raise AssertionError(
            "Inference subprocess timed out after 120s — the LLM backend may be unresponsive."
        ) from None
    except AssertionError:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger inference: {e}")
        raise AssertionError(f"Inference failed: {e}") from e

    logger.info("Inference completed. Waiting for traces to propagate to Tempo...")

    tempo_search_url = "http://127.0.0.1:3200/api/search?limit=100"
    max_retries = 3
    found_e2e_trace = False
    required_services = {"openclaw-gateway", "litellm", "vllm-main"}

    async with httpx.AsyncClient() as client:
        for attempt in range(max_retries):
            # Wait for traces to flush
            await asyncio.sleep(15)

            try:
                response = await client.get(tempo_search_url, timeout=10)
                response.raise_for_status()
                traces = response.json().get("traces", [])
            except Exception as e:
                logger.error(f"Failed to query Tempo search API: {e}")
                if attempt == max_retries - 1:
                    raise AssertionError(f"Failed to query Tempo: {e}") from e
                continue

            if not traces:
                logger.debug("No traces found in Tempo yet, retrying...")
                continue

            for trace in traces:
                trace_id = trace["traceID"]
                try:
                    trace_resp = await client.get(
                        f"http://127.0.0.1:3200/api/traces/{trace_id}", timeout=10
                    )
                    trace_resp.raise_for_status()
                    trace_data = trace_resp.json()
                except Exception as e:
                    logger.debug(f"Failed to fetch trace {trace_id}: {e}")
                    continue

                services_in_trace = set()
                for batch in trace_data.get("batches", []):
                    resource = batch.get("resource", {})
                    for attr in resource.get("attributes", []):
                        if attr.get("key") == "service.name":
                            services_in_trace.add(attr.get("value", {}).get("stringValue"))

                if services_in_trace:
                    logger.info(f"Trace {trace_id} has services: {services_in_trace}")

                if required_services.issubset(services_in_trace):
                    # Check payload length
                    max_len = 0
                    for batch in trace_data.get("batches", []):
                        for scope in batch.get("scopeSpans", []):
                            for span in scope.get("spans", []):
                                for attr in span.get("attributes", []):
                                    if attr.get("key") == "gen_ai.input.messages":
                                        length = len(attr.get("value", {}).get("stringValue", ""))
                                        max_len = max(max_len, length)

                    if max_len > 0:
                        logger.info(
                            f"✅ Pass: E2E Trace {trace_id} successfully linked across {required_services}!"
                        )
                        logger.info(
                            f"✅ Pass: Found gen_ai.input.messages with length {max_len} (> 0)!"
                        )
                        found_e2e_trace = True
                        break
                    logger.warning(
                        f"Found trace {trace_id} with required services, but max gen_ai.input.messages length was only {max_len}. Expected > 0. Skipping."
                    )

            if found_e2e_trace:
                break

        if not found_e2e_trace:
            logger.error(
                f"❌ Failure: Could not find a single trace containing all required services: {required_services} with correct payload size."
            )
            raise AssertionError("E2E Trace verification failed.")
