import json
import re
import time
import uuid

import pytest
from loguru import logger

from core.utils import async_run_command
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import cleanup_session


@pytest.mark.order(7)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_consumer_readiness(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_{int(time.time())}_{unique_token[:8]}"
    tool_cmd = [
        str(ctx.oc_bin),
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
        json_match = re.search(r"(\{.*\})", output, re.DOTALL)
        if not json_match:
            logger.error(
                f"❌ Failure: No JSON payload found in output.\nRaw Output:\n{output[:500]}"
            )
            raise AssertionError()

        try:
            data = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failure: Invalid JSON payload: {e}")
            raise AssertionError() from None

        # 2. Check turn status
        if data.get("status") != "ok":
            logger.error(
                f"❌ Failure: Agent status is '{data.get('status')}'. Summary: {data.get('summary')}"
            )
            raise AssertionError() from None

        # 3. Verify response content
        result = data.get("result", {})
        payloads = result.get("payloads", [])
        assistant_text = " ".join(p.get("text", "") for p in payloads)

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
