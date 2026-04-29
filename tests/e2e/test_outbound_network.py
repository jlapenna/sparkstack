import json
import re
import time
import uuid

import pytest
from loguru import logger

from core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(4)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_outbound_network(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_net_{int(time.time())}_{unique_token[:8]}"

    prompt = (
        "Use your bash tool or python tool to fetch exactly this URL: "
        "`https://httpbin.org/uuid` and reply to me with ONLY the JSON output that you received."
    )

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

    logger.info(f"Requesting network fetch in session {session_id} (timeout 300s)...")
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

    if "uuid" not in assistant_text.lower():
        logger.error(
            f"❌ Failure: Agent could not successfully return the network payload.\nResponse: {assistant_text}"
        )
        raise AssertionError() from None

    logger.info("✅ Pass: Outbound Network Integrity (Agent successfully egressed to internet)")
    return
