import json
import re
import time
import uuid

import pytest
from loguru import logger

from core.utils import async_run_command
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import cleanup_session


@pytest.mark.order(11)
@pytest.mark.timeout(900)
@pytest.mark.asyncio
async def test_long_conversation(ctx: E2EContext):
    """
    Validates that an agent can handle a 30-message back-and-forth
    without failing, hanging, or dropping context.
    """
    unique_token = str(uuid.uuid4())[:8]
    session_id = f"verifier_long_{int(time.time())}_{unique_token}"

    total_messages = 30

    try:
        logger.info(f"Starting {total_messages}-message conversation test in session: {session_id}")

        for i in range(1, total_messages + 1):
            prompt = f"Message {i} of {total_messages}. Please reply with ONLY the exact string 'ACK_{i}'."

            tool_cmd = [
                str(ctx.oc_bin),
                "agent",
                "--agent",
                "verifier",
                "--session-id",
                session_id,
                "--message",
                prompt,
                "--json",
            ]

            start_time = time.time()
            res = await async_run_command(tool_cmd, check=False)
            output = res.stdout + res.stderr
            elapsed = time.time() - start_time

            json_match = re.search(r"(\{.*\})", output, re.DOTALL)
            if not json_match:
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: No JSON payload found in output. Raw Output: {output[:500]}"
                )
                raise AssertionError(f"Message {i} failed: No JSON payload")

            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: Invalid JSON payload: {e}"
                )
                raise AssertionError(f"Message {i} failed: JSON Decode Error") from None

            if data.get("status") != "ok":
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: Agent status is '{data.get('status')}'. Summary: {data.get('summary')}"
                )
                raise AssertionError(f"Message {i} failed: Non-ok status") from None

            result = data.get("result", {})
            payloads = result.get("payloads", [])
            assistant_text = " ".join(p.get("text", "") for p in payloads)

            expected_response = f"ACK_{i}"
            if expected_response not in assistant_text:
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: Unexpected agent reply.\n"
                    f"Expected: {expected_response}\nResponse: {assistant_text}"
                )
                raise AssertionError(f"Message {i} failed: Bad response") from None

            logger.info(f"Message {i}/{total_messages} OK (Elapsed: {elapsed:.2f}s)")

        logger.info(
            f"✅ Pass: Long Conversation Verification (Successfully completed {total_messages} turns)"
        )
    finally:
        cleanup_session(session_id)
