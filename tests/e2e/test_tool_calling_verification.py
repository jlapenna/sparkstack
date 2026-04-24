import json
import re
import time
import uuid

import pytest
from loguru import logger

from core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.asyncio
async def test_tool_calling_verification(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_tool_{int(time.time())}_{unique_token[:8]}"

    prompt = (
        f"Use your bash tool or command execution tool to run the following command exactly: "
        f"`echo 'tool_check_{unique_token}'`. "
        f"Then reply to me with ONLY the output you see from the tool."
    )

    tool_cmd = [
        str(ctx.oc_bin),
        "agent",
        "--agent",
        "jclaw",
        "--session-id",
        session_id,
        "--message",
        prompt,
        "--json",
    ]

    logger.info(f"Requesting tool execution in session {session_id} (timeout 300s)...")
    res_tool = await async_run_command(tool_cmd, check=False)
    output = res_tool.stdout + res_tool.stderr

    json_match = re.search(r"(\{.*\})", output, re.DOTALL)
    if not json_match:
        logger.error(f"❌ Failure: No JSON payload found in output.\nRaw Output:\n{output[:500]}")
        raise AssertionError()

    try:
        data = json.loads(json_match.group(1))
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failure: Invalid JSON payload: {e}")
        raise AssertionError() from None

    if data.get("status") != "ok":
        logger.error(
            f"❌ Failure: Agent status is '{data.get('status')}'. Summary: {data.get('summary')}"
        )
        raise AssertionError() from None

    result = data.get("result", {})
    payloads = result.get("payloads", [])
    assistant_text = " ".join(p.get("text", "") for p in payloads)

    expected_response = f"tool_check_{unique_token}"
    if expected_response not in assistant_text:
        logger.error(
            f"❌ Failure: Agent could not successfully return the tool output.\nExpected: {expected_response}\nResponse: {assistant_text}"
        )
        raise AssertionError() from None

    logger.info(
        "✅ Pass: Tool Calling Verification (Agent successfully executed and returned tool output)"
    )
    return
