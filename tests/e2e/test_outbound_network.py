import time
import uuid

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command, parse_cli_json
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

    logger.info(f"Requesting network fetch in session {session_id} (timeout 300s)...")
    res_tool = await async_run_command(tool_cmd, check=False)
    output = res_tool.stdout + res_tool.stderr

    try:
        data = parse_cli_json(output)
        assert isinstance(data, dict)
    except (ValueError, AssertionError) as e:
        logger.error(f"❌ Failure: {e}\nRaw Output:\n{output[:500]}")
        raise AssertionError() from None

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
        assistant_text = result.get("finalAssistantVisibleText", "") or ""

    if "uuid" not in assistant_text.lower():
        logger.error(
            f"❌ Failure: Agent could not successfully return the network payload.\nResponse: {assistant_text}"
        )
        raise AssertionError() from None

    logger.info("✅ Pass: Outbound Network Integrity (Agent successfully egressed to internet)")
    return
