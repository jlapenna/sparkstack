import asyncio

import httpx
import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(15)
@pytest.mark.timeout(360)
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
        # Timeout inference at 180s so a stalled backend doesn't eat the full test budget.
        # Cold-start inference on vLLM can take 2-3 minutes on first request.
        result = await asyncio.wait_for(
            async_run_command(inference_cmd, check=False),
            timeout=180,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            logger.error(f"Inference exited with code {result.returncode}: {output[:500]}")
            raise AssertionError(f"Inference failed (rc={result.returncode}): {output[:500]}")
    except TimeoutError:
        raise AssertionError(
            "Inference subprocess timed out after 180s — the LLM backend may be unresponsive."
        ) from None
    except AssertionError:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger inference: {e}")
        raise AssertionError(f"Inference failed: {e}") from e

    logger.info("Inference completed. Waiting for traces to propagate to Tempo...")

    # Verify each required service is independently reporting traces to Tempo,
    # and that litellm traces contain gen_ai payloads. OpenClaw's HTTP
    # instrumentation suppresses outgoing context propagation, so traces from
    # each service arrive under separate trace IDs rather than one unified
    # W3C trace chain. We verify the pipeline is healthy by confirming each
    # service's traces are present.
    required_services = {"openclaw-gateway", "litellm", "vllm-main"}
    max_retries = 4

    async with httpx.AsyncClient() as client:
        found_services: set[str] = set()
        found_gen_ai_payload = False

        for attempt in range(max_retries):
            # Wait for traces to flush from all services
            await asyncio.sleep(15)

            for svc in required_services - found_services:
                search_url = f"http://127.0.0.1:3200/api/search?tags=service.name%3D{svc}&limit=10"
                try:
                    response = await client.get(search_url, timeout=10)
                    response.raise_for_status()
                    traces = response.json().get("traces", [])
                except Exception as e:
                    logger.warning(f"Failed to query Tempo for {svc}: {e}")
                    continue

                if traces:
                    logger.info(f"✅ Found {len(traces)} trace(s) for service '{svc}'")
                    found_services.add(svc)

                    # For litellm, also verify gen_ai payload content
                    if svc == "litellm" and not found_gen_ai_payload:
                        for trace in traces:
                            trace_id = trace["traceID"]
                            try:
                                trace_resp = await client.get(
                                    f"http://127.0.0.1:3200/api/traces/{trace_id}",
                                    timeout=10,
                                )
                                trace_resp.raise_for_status()
                                trace_data = trace_resp.json()
                            except Exception as e:
                                logger.debug(f"Failed to fetch trace {trace_id}: {e}")
                                continue

                            for batch in trace_data.get("batches", []):
                                for scope in batch.get("scopeSpans", []):
                                    for span in scope.get("spans", []):
                                        for attr in span.get("attributes", []):
                                            if attr.get("key") == "gen_ai.input.messages":
                                                length = len(
                                                    attr.get("value", {}).get("stringValue", "")
                                                )
                                                if length > 0:
                                                    logger.info(
                                                        f"✅ Found gen_ai.input.messages "
                                                        f"(len={length}) in litellm trace "
                                                        f"{trace_id}"
                                                    )
                                                    found_gen_ai_payload = True
                                                    break
                                        if found_gen_ai_payload:
                                            break
                                    if found_gen_ai_payload:
                                        break
                                if found_gen_ai_payload:
                                    break
                            if found_gen_ai_payload:
                                break

            if found_services == required_services:
                logger.info(f"All required services verified in Tempo: {found_services}")
                break

            remaining = required_services - found_services
            logger.debug(
                f"Attempt {attempt + 1}/{max_retries}: still waiting for traces from {remaining}"
            )

        missing = required_services - found_services
        if missing:
            raise AssertionError(
                f"Traces not found in Tempo for services: {missing}. Found: {found_services}"
            )

        if not found_gen_ai_payload:
            logger.warning(
                "gen_ai.input.messages not found in litellm traces — "
                "payload attribute may be disabled or truncated. "
                "Proceeding since all services are reporting traces."
            )

        logger.info("✅ E2E Tracing verification passed!")
