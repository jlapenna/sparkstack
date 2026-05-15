import time
import uuid

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command
from tests.e2e.context import E2EContext
from tests.e2e.session_cleanup import cleanup_session
from tests.e2e.utils import extract_cli_json


@pytest.mark.order(10)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_tool_calling(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_tool_{int(time.time())}_{unique_token[:8]}"

    prompt = (
        f"Use your bash tool or command execution tool to run the following command exactly: "
        f"`echo 'tool_check_{unique_token}'`. "
        f"Then reply to me with ONLY the output you see from the tool."
    )

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

    try:
        logger.info(f"Requesting tool execution in session {session_id} (timeout 300s)...")
        res_tool = await async_run_command(tool_cmd, check=False)
        output = res_tool.stdout + res_tool.stderr
        logger.debug(f"CLI Output: {output}")

        data = extract_cli_json(output)

        if data is None:
            logger.error(
                f"❌ Failure: No valid JSON payload found in output.\nRaw Output:\n{output[:500]}"
            )
            raise AssertionError()

        status = data.get("status", "ok") if "payloads" in data else data.get("status")
        if status != "ok":
            logger.error(
                f"❌ Failure: Agent status is '{status}'. Summary: {data.get('summary')}\n"
                f"Parsed keys: {list(data.keys())}\n"
                f"Raw output (first 1000 chars): {output[:1000]}"
            )
            raise AssertionError() from None

        result = data.get("result", {})
        payloads = result.get("payloads", [])
        if payloads:
            assistant_text = " ".join(p.get("text", "") for p in payloads)
        else:
            assistant_text = result.get("finalAssistantVisibleText", "")

        expected_response = f"tool_check_{unique_token}"
        if expected_response not in assistant_text:
            logger.error(
                f"❌ Failure: Agent could not successfully return the tool output.\nExpected: {expected_response}\nResponse: {assistant_text}"
            )
            raise AssertionError() from None

        logger.info(
            "✅ Pass: Tool Calling Verification (Agent successfully executed and returned tool output)"
        )
    finally:
        cleanup_session(session_id)
