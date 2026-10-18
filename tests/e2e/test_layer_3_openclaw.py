import time
import uuid

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command, parse_cli_json
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import cleanup_session
from tests.e2e.utils import extract_cli_json


@pytest.mark.order(6)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_layer_3_openclaw(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_{int(time.time())}_{unique_token[:8]}"
    tool_cmd = [
        str(ctx.openclaw_bin),
        "agent",
        "--agent",
        "verifier",
        "--session-id",
        session_id,
        "--message",
        f"Please repeat exactly this unique string back to me: {unique_token}",
        "--json",
    ]

    try:
        logger.info(f"Requesting turn in session {session_id} (timeout 300s)...")
        res_tool = await async_run_command(tool_cmd, check=False)
        output = res_tool.stdout + res_tool.stderr

        # 1. Parse JSON result
        data = extract_cli_json(output)

        if data is None:
            logger.error(
                f"❌ Failure: No JSON payload found in output.\nRaw Output:\n{output[:500]}"
            )
            raise AssertionError()

        # 2. Check turn status
        status = data.get("status", "ok") if "payloads" in data else data.get("status")
        if status != "ok":
            logger.error(
                f"❌ Failure: Agent status is '{status}'. Summary: {data.get('summary')}\n"
                f"Parsed keys: {list(data.keys())}\n"
                f"Raw output (first 1000 chars): {output[:1000]}"
            )
            raise AssertionError() from None

        # 3. Verify response content
        result = data.get("result", {})
        payloads = result.get("payloads", [])
        if payloads:
            assistant_text = " ".join(p.get("text", "") for p in payloads)
        else:
            assistant_text = result.get("finalAssistantVisibleText", "")

        # Error string check
        failure_indicators = ["LLM request failed", "network connection error", "Connection error"]
        for indicator in failure_indicators:
            if indicator.lower() in assistant_text.lower():
                logger.error(f"❌ Failure: Response indicates LLM error: '{indicator}'")
                raise AssertionError() from None

        # Semantic check (The unique_token should be in the response)
        if unique_token not in assistant_text:
            logger.error(
                f"❌ Failure: Agent gave unexpected answer (missing UUID).\nResponse: {assistant_text}"
            )
            raise AssertionError() from None

        logger.info("✅ Pass: Consumer Readiness (Verified agent turnaround and reasoning)")
    finally:
        cleanup_session(session_id)


@pytest.mark.order(9)
@pytest.mark.asyncio
async def test_openclaw_models_list_spark_main(ctx: E2EContext):
    """OpenClaw's model catalog must expose the ``spark/main`` key."""
    result = await async_run_command([str(ctx.openclaw_bin), "models", "list", "--json"])
    data = parse_cli_json(result.stdout)
    assert isinstance(data, dict), "no JSON object in 'openclaw models list' output"
    spark_models = [
        m["key"] for m in data.get("models", []) if m.get("key", "").startswith("spark/")
    ]
    logger.info(f"Configured Spark models: {', '.join(spark_models)}")
    assert "spark/main" in spark_models, "spark/main not found in OpenClaw"
