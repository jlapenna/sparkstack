import asyncio
import time
import uuid

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import cleanup_session
from tests.e2e.utils import extract_cli_json


@pytest.mark.order(11)
@pytest.mark.timeout(3600)
@pytest.mark.asyncio
async def test_long_conversation(ctx: E2EContext):
    """
    Validates that an agent can handle a 4-message back-and-forth
    without failing, hanging, or dropping context.
    """
    unique_token = str(uuid.uuid4())[:8]
    session_id = f"verifier_long_{int(time.time())}_{unique_token}"

    total_messages = ctx.long_conversation_messages

    try:
        logger.info(f"Starting {total_messages}-message conversation test in session: {session_id}")

        for i in range(1, total_messages + 1):
            prompt = f"Message {i} of {total_messages}. This is NOT a heartbeat check. You MUST reply with ONLY the exact string 'ACK_{i}'. Do not reply HEARTBEAT_OK."

            tool_cmd = [
                str(ctx.openclaw_bin),
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
            # 1. Extract JSON Payload
            data = extract_cli_json(output)

            if data is None:
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: No JSON payload found in output. Raw Output: {output[:500]}"
                )
                raise AssertionError(f"Message {i} failed: JSON Decode Error") from None

            status = data.get("status", "ok") if "payloads" in data else data.get("status")
            if status != "ok":
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: Agent status is '{status}'. "
                    f"Summary: {data.get('summary')}\n"
                    f"JSON keys: {list(data.keys())}\n"
                    f"Raw output (500 chars): {output[:500]}"
                )
                raise AssertionError(f"Message {i} failed: Non-ok status") from None

            result = data.get("result", {})
            payloads = result.get("payloads", [])
            if payloads:
                assistant_text = " ".join(p.get("text", "") for p in payloads)
            else:
                assistant_text = result.get("finalAssistantVisibleText", "")

            expected_response = f"ACK_{i}"
            if expected_response not in assistant_text:
                logger.error(
                    f"❌ Failure on message {i}/{total_messages}: Unexpected agent reply.\n"
                    f"Expected: {expected_response}\nResponse: {assistant_text}"
                )
                raise AssertionError(f"Message {i} failed: Bad response") from None

            logger.info(f"Message {i}/{total_messages} OK (Elapsed: {elapsed:.2f}s)")
            await asyncio.sleep(2)  # Reduce gateway saturation

        logger.info(
            f"✅ Pass: Long Conversation Verification (Successfully completed {total_messages} turns)"
        )
    finally:
        cleanup_session(session_id)
