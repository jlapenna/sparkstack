#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import asyncio
import json
from pathlib import Path

from loguru import logger

from sparkstack.core.env import OPENCLAW_CONFIG_DIR, OPENCLAW_CONFIG_PATH, PROJECT_ROOT
from sparkstack.core.schemas import (
    OpenClawConfig,
    SparkProvider,
)


async def sync_registry(
    project_root: Path = PROJECT_ROOT, config_path: Path = OPENCLAW_CONFIG_PATH
) -> None:
    logger.info("Syncing models to openclaw.json...")
    models_json = (project_root / "current").resolve() / "models.json"
    if not models_json.exists():
        logger.warning(f"Source models.json missing at {models_json}")
        return

    source_data_str = await asyncio.to_thread(models_json.read_text)
    source_data = json.loads(source_data_str)
    spark_source = source_data.get("spark", {})

    # Load existing config raw
    if config_path.exists():
        config_str = await asyncio.to_thread(config_path.read_text)
        config_dict = json.loads(config_str)
    else:
        config_dict = {}

    openclaw_config = OpenClawConfig.model_validate(config_dict)

    # Build Spark provider
    provider_model = SparkProvider.model_validate(spark_source)

    # Update provider, agents, and models using the encapsulated method
    openclaw_config.update_from_spark_provider(provider_model)

    # Save back raw JSON, preserving all unstructured fields perfectly
    dumped_config = openclaw_config.model_dump(by_alias=True, exclude_none=True)
    await asyncio.to_thread(config_path.write_text, json.dumps(dumped_config, indent=2) + "\n")
    logger.info("openclaw.json synchronized correctly.")

    # Purge stale agent-level models.json overrides to prevent configuration drift
    agents_dir = OPENCLAW_CONFIG_DIR / "agents"
    if agents_dir.is_dir():
        for agent_models_path in agents_dir.glob("*/agent/models.json"):
            try:
                agent_models_path.unlink(missing_ok=True)
                logger.info(f"Purged stale agent override: {agent_models_path.parent.parent.name}")
            except OSError as e:
                logger.warning(f"Failed to purge {agent_models_path}: {e}")


if __name__ == "__main__":
    asyncio.run(sync_registry())
