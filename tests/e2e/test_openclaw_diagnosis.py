import json
import re

import pytest
from loguru import logger

from core.utils import async_run_command
from tests.e2e.context import E2EContext


@pytest.mark.order(9)
@pytest.mark.asyncio
async def test_openclaw_diagnosis(ctx: E2EContext):
    result = await async_run_command([str(ctx.oc_bin), "models", "list", "--json"])
    match = re.search(r"\{.*\}", result.stdout, re.DOTALL)
    if not match:
        logger.error("❌ Could not find JSON in 'openclaw models list' output")
        raise AssertionError()

    data = json.loads(match.group(0))
    models = data.get("models", [])
    spark_models = [m["key"] for m in models if m.get("key", "").startswith("spark/")]
    logger.info(f"Configured Spark models: {', '.join(spark_models)}")

    if any(m == "spark/main" for m in spark_models):
        logger.info("✅ Pass: OpenClaw System Diagnosis")
        return
    else:
        logger.error("❌ Failure: spark/main not found in OpenClaw")
        raise AssertionError()
