from loguru import logger
from scripts.check_memory_law import check_compliance
from scripts.verify.utils import verify_layer
from scripts.verify.context import VerifyContext


@verify_layer("Layer 0: Hardware Constraint Verification")
async def run(ctx: VerifyContext):
    passed = await check_compliance(log_output=True)
    if not passed:
        logger.error("❌ Failure: Stack deployment exceeds physics limits.")
        return False
    logger.info("✅ Pass: Physics validation (RAM/VRAM boundaries honored)")
    return True
