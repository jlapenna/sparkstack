import time
import uuid

import pytest
from loguru import logger

from sparkstack.core.utils import async_run_command, parse_cli_json
from tests.e2e.context import E2EContext


@pytest.mark.order(12)
@pytest.mark.timeout(300)
@pytest.mark.asyncio
async def test_workspace_io(ctx: E2EContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_fs_{int(time.time())}_{unique_token[:8]}"
    filename = f"tmp/workspace_verification_{unique_token[:8]}.txt"

    prompt_write = (
        f"Use your bash tool or file tool to write exactly this string: '{unique_token}' "
        f"to a file at path '{filename}' relative to your active current directory. "
        f"Create the 'tmp' directory if it doesn't already exist. "
        f"Confirm ONLY with 'DONE' when the file is written."
    )

    cmd_write = [
        str(ctx.openclaw_bin),
        "agent",
        "--agent",
        "verifier",
        "--session-id",
        session_id,
        "--message",
        prompt_write,
        "--json",
    ]

    logger.info(f"Requesting workspace write in session {session_id}...")
    await async_run_command(cmd_write, check=False)

    prompt_read = (
        f"Now, read the file '{filename}' back into memory. "
        f"After reading it, you MUST delete the file '{filename}'. "
        f"Reply to me with ONLY the EXACT string you read from the file."
    )

    cmd_read = [
        str(ctx.openclaw_bin),
        "agent",
        "--agent",
        "verifier",
        "--session-id",
        session_id,
        "--message",
        prompt_read,
        "--json",
    ]

    logger.info(f"Requesting workspace read in session {session_id}...")
    res_tool = await async_run_command(cmd_read, check=False)
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
        assistant_text = result.get("finalAssistantVisibleText", "")

    if unique_token not in assistant_text:
        logger.error(
            f"❌ Failure: Agent could not successfully verify File IO with UUID.\nExpected: {unique_token}\nResponse: {assistant_text}"
        )
        raise AssertionError() from None

    logger.info("✅ Pass: File System Integrity (Agent successfully executed workspace I/O)")
    return
