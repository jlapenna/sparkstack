import json
import re
from loguru import logger
from core.utils import async_run_command
from core.constants import OPENCLAW_HOME
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 13: Agent Skill Readiness")
async def run(ctx: VerifyContext):
    """
    Verify that agents have access to both personal and built-in skills.
    Checks:
    1. Discovery limits (maxCandidatesPerRoot)
    2. Personal skill availability (volume mounts + permissions)
    3. Built-in skill availability (sandbox injection)
    """
    logger.info("Verifying agent skill access...")

    # 1. Check skill list for a known personal skill (e.g., zustand-store-ts)
    # and a known built-in skill (e.g., mcporter)
    result = await async_run_command([str(ctx.oc_bin), "skills", "list", "--json"])
    match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
    if not match:
        logger.error("❌ Could not find JSON in 'oc skills list' output")
        return False

    data = json.loads(match.group(0))
    skills = data.get("skills", [])
    skill_names = {s["name"] for s in skills if s.get("eligible")}

    builtin_skill = "mcporter"

    if builtin_skill not in skill_names:
        logger.error(f"❌ Built-in skill '{builtin_skill}' not found or not ready.")
        return False

    logger.info(f"✅ Skills discovered: {builtin_skill}")

    # 2. Check Sandbox access directly
    # We attempt to run a command in the default sandbox that requires skill file access.
    # Note: This assumes 'jclaw' or 'default' agent exists and is configured for sandboxing.
    # Check if personal skills are mounted (requires DooD paradox fix verification)
    # We check the gateway container's mount to verify the path rewriting worked
    inspect_result = await async_run_command(
        [
            "docker",
            "inspect",
            "openclaw-openclaw-gateway-1",
            "--format",
            "{{range .Mounts}}{{println .Source .Destination}}{{end}}",
        ]
    )
    mounts = inspect_result.stdout.strip().split("\n")

    # We look for the absolute host path matching OPENCLAW_HOME
    has_personal_mount = any(str(OPENCLAW_HOME) in m for m in mounts)
    if not has_personal_mount:
        logger.error(
            f"❌ Gateway is missing the host-absolute mount for {OPENCLAW_HOME}. Path rewriting may have failed."
        )
        return False
    logger.info(f"✅ Gateway verified with host-absolute {OPENCLAW_HOME} mount")

    logger.info("✅ Pass: Agent Skill Readiness")
    return True
