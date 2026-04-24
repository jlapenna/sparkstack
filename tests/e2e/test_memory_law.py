import pytest
from loguru import logger

from scripts.check_memory_law import check_compliance
from tests.e2e.context import E2EContext


@pytest.mark.asyncio
@pytest.mark.order(1)
async def test_memory_law(ctx: E2EContext):
    passed = await check_compliance(log_output=True)
    if not passed:
        logger.error("❌ Failure: Stack deployment exceeds physics limits.")
        raise AssertionError()
    logger.info("✅ Pass: Physics validation (RAM/VRAM boundaries honored)")
    return
