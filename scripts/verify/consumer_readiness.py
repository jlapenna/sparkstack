import uuid
import time
import re
import json
from loguru import logger
from core.utils import async_run_command
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 5: Consumer Readiness (End-to-End)")
async def run(ctx: VerifyContext):
    unique_token = str(uuid.uuid4())
    session_id = f"verifier_{int(time.time())}_{unique_token[:8]}"
    tool_cmd = [
        str(ctx.oc_bin),
        "agent",
        "--agent",
        "jclaw",
        "--session-id",
        session_id,
        "--message",
        f"Please repeat exactly this unique string back to me: {unique_token}",
        "--json",
    ]
    logger.info(f"Requesting turn in session {session_id} (timeout 300s)...")
    res_tool = await async_run_command(tool_cmd, check=False)
    output = res_tool.stdout + res_tool.stderr

    # 1. Parse JSON result
    json_match = re.search(r"(\{.*\})", output, re.DOTALL)
    if not json_match:
        logger.error(f"❌ Failure: No JSON payload found in output.\nRaw Output:\n{output[:500]}")
        return False

    try:
        data = json.loads(json_match.group(1))
    except json.JSONDecodeError as e:
        logger.error(f"❌ Failure: Invalid JSON payload: {e}")
        return False

    # 2. Check turn status
    if data.get("status") != "ok":
        logger.error(
            f"❌ Failure: Agent status is '{data.get('status')}'. Summary: {data.get('summary')}"
        )
        return False

    # 3. Verify response content
    result = data.get("result", {})
    payloads = result.get("payloads", [])
    assistant_text = " ".join(p.get("text", "") for p in payloads)

    # Error string check
    failure_indicators = ["LLM request failed", "network connection error", "Connection error"]
    for indicator in failure_indicators:
        if indicator.lower() in assistant_text.lower():
            logger.error(f"❌ Failure: Response indicates LLM error: '{indicator}'")
            return False

    # Semantic check (The unique_token should be in the response)
    if unique_token not in assistant_text:
        logger.error(
            f"❌ Failure: Agent gave unexpected answer (missing UUID).\nResponse: {assistant_text}"
        )
        return False

    logger.info("✅ Pass: Consumer Readiness (Verified agent turnaround and reasoning)")
    return True
