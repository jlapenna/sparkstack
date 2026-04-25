#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import asyncio
import json
import sys
from pathlib import Path

import yaml
from loguru import logger

from core.constants import (
    MAX_DOCKER_MEMORY_GB,
    MAX_VRAM_UTILIZATION,
    USABLE_SPARK_MEMORY_GB,
)
from core.utils import async_run_command

# Root directory for resolving local paths
ROOT_DIR = Path(__file__).parent.parent.absolute()


async def get_docker_stats() -> list[dict]:
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
    result = await async_run_command(cmd, check=True)
    stats = []
    for line in result.stdout.strip().split("\n"):
        if line:
            stats.append(json.loads(line))
    return stats


def parse_mem_usage(mem_str: str) -> float:
    try:
        # Format: "1.23GiB / 3.45GiB" or "500MiB / 1GiB"
        usage_part = mem_str.split(" / ")[0].strip()
        if usage_part.endswith("GiB") or usage_part.endswith("GB"):
            return float(usage_part[:-3])
        elif usage_part.endswith("MiB") or usage_part.endswith("MB"):
            return float(usage_part[:-3]) / 1024.0
        elif usage_part.endswith("KiB") or usage_part.endswith("KB"):
            return float(usage_part[:-3]) / (1024.0 * 1024.0)
        elif usage_part.endswith("B"):
            return float(usage_part[:-1]) / (1024.0 * 1024.0 * 1024.0)
        return 0.0
    except Exception:
        logger.exception(f"Failed to parse memory string '{mem_str}'")
        return 0.0


async def get_vram_estimate(recipe: str) -> float:
    """Returns the estimated VRAM footprint in GB using sparkrun vram estimation."""
    try:
        sparkrun_bin = ROOT_DIR / ".venv" / "bin" / "sparkrun"
        if not sparkrun_bin.exists():
            # If standard setup is bypassed, fallback to regular sparkrun
            sparkrun_bin = "sparkrun"

        cmd_recipe = recipe
        local_recipe = ROOT_DIR / "spark-stack-registry" / "sparkrun" / f"{recipe}.yaml"
        if local_recipe.exists():
            cmd_recipe = str(local_recipe)

        cmd = [str(sparkrun_bin), "recipe", "vram", cmd_recipe, "--json", "--tp", "1"]
        result = await async_run_command(cmd, check=False)
        if result.returncode == 0 and result.stdout.strip():
            vram_data = json.loads(result.stdout)
            vram_gb = vram_data.get("usable_gpu_memory_gb") or vram_data.get(
                "total_per_gpu_gb", 0.0
            )
            return float(vram_gb)
    except Exception:
        logger.debug(f"Failed to estimate VRAM for recipe {recipe}")
    return 0.0


async def get_active_recipes() -> set[str]:
    """Inspects litellm configurations to find active recipes/models deployed."""
    litellm_config = ROOT_DIR / "current" / "litellm-config.yaml"
    recipes = set()
    if not litellm_config.exists():
        return recipes

    try:
        with open(litellm_config) as f:
            config = yaml.safe_load(f)

        for m in config.get("model_list", []):
            info = m.get("model_info", {})
            recipe = info.get("db_model") or info.get("base_model")
            if recipe:
                recipes.add(recipe)
    except Exception:
        logger.exception("Failed to parse litellm-config.yaml for active recipes")

    return recipes


async def check_compliance(log_output: bool = True) -> bool:
    if log_output:
        logger.info(
            f"🔍 Checking Memory Law compliance...\n"
            f"   - RAM Ceiling: {MAX_DOCKER_MEMORY_GB}GB\n"
            f"   - VRAM Utilization Ceiling: {MAX_VRAM_UTILIZATION * 100:.1f}% of {USABLE_SPARK_MEMORY_GB}GB"
        )

    try:
        # 1. Evaluate Host Shared Memory (RAM)
        stats = await get_docker_stats()
        total_ram = 0.0

        if log_output:
            logger.info("\n" + "=" * 50)
            logger.info(f"{'Docker Container':<30} {'RAM Usage':<15}")
            logger.info("-" * 50)
        for s in stats:
            usage = round(parse_mem_usage(s["MemUsage"]), 2)
            total_ram += usage
            if log_output:
                logger.info(f"{s['Name']:<30} {usage:>10.2f} GB")
        if log_output:
            logger.info("-" * 50)
            logger.info(f"{'TOTAL RAM AGGREGATE':<30} {total_ram:>10.2f} GB")

        # 2. Evaluate GPU VRAM Estimates
        recipes = await get_active_recipes()
        total_vram = 0.0
        if log_output:
            logger.info("\n" + "=" * 50)
            logger.info(f"{'Active Recipe':<30} {'VRAM Est.':<15}")
            logger.info("-" * 50)

        for recipe in recipes:
            vram = round(await get_vram_estimate(recipe), 2)
            total_vram += vram
            if log_output:
                logger.info(f"{recipe:<30} {vram:>10.2f} GB")

        if log_output:
            logger.info("-" * 50)
            logger.info(f"{'TOTAL VRAM AGGREGATE':<30} {total_vram:>10.2f} GB")
            logger.info("=" * 50 + "\n")

        # 3. Formulate Verdicts
        vram_utilization = total_vram / USABLE_SPARK_MEMORY_GB if USABLE_SPARK_MEMORY_GB > 0 else 0
        breached = False

        if total_ram > MAX_DOCKER_MEMORY_GB:
            logger.error(f"❌ RAM Law BREACHED! ({total_ram:.2f}GB > {MAX_DOCKER_MEMORY_GB}GB)")
            breached = True

        if vram_utilization > MAX_VRAM_UTILIZATION:
            logger.error(
                f"❌ VRAM Law BREACHED! Utilization is {vram_utilization * 100:.1f}% "
                f"({total_vram:.2f}GB) which exceeds {MAX_VRAM_UTILIZATION * 100:.1f}%."
            )
            breached = True

        if breached:
            return False
        else:
            if log_output:
                logger.success("✅ Memory Law compliant across both RAM and VRAM dimensions.")
            return True

    except Exception:
        logger.exception("Error running memory check")
        return False


async def main():
    if not await check_compliance(log_output=True):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, format="<level>{message}</level>")
    asyncio.run(main())
