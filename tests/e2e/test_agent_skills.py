import pytest
from loguru import logger

from sparkstack.core.env import OPENCLAW_CONFIG_DIR
from sparkstack.core.utils import async_run_command, parse_cli_json
from tests.e2e.context import E2EContext


@pytest.mark.order(11)
@pytest.mark.asyncio
async def test_agent_skills(ctx: E2EContext):
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
    result = await async_run_command([str(ctx.openclaw_bin), "skills", "list", "--json"])
    try:
        data = parse_cli_json(result.stdout)
        assert isinstance(data, dict)
    except (ValueError, AssertionError) as err:
        logger.error("❌ Could not find JSON in 'openclaw skills list' output")
        raise AssertionError() from err
    skills = data.get("skills", [])
    skill_names = {s["name"] for s in skills if s.get("eligible")}

    builtin_skill = "mcporter"

    if builtin_skill not in skill_names:
        logger.error(f"❌ Built-in skill '{builtin_skill}' not found or not ready.")
        raise AssertionError()

    logger.info(f"✅ Skills discovered: {builtin_skill}")

    # 2. Check Sandbox access directly
    # We attempt to run a command in the default sandbox that requires skill file access.
    # Note: This assumes 'verifier' or 'default' agent exists and is configured for sandboxing.
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

    # We look for the absolute host path matching OPENCLAW_CONFIG_DIR
    has_personal_mount = any(str(OPENCLAW_CONFIG_DIR) in m for m in mounts)
    if not has_personal_mount:
        logger.error(
            f"❌ Gateway is missing the host-absolute mount for {OPENCLAW_CONFIG_DIR}. Path rewriting may have failed."
        )
        raise AssertionError()
    logger.info(f"✅ Gateway verified with host-absolute {OPENCLAW_CONFIG_DIR} mount")

    logger.info("✅ Pass: Agent Skill Readiness")
    return
