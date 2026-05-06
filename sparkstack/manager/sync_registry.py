#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import asyncio
import json
import os
from pathlib import Path

from loguru import logger

from sparkstack.core.env import OPENCLAW_CONFIG_DIR, OPENCLAW_CONFIG_PATH, PROJECT_ROOT
from sparkstack.core.schemas import SparkProvider


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
        config = json.loads(config_str)
    else:
        config = {}

    # Update providers
    models = config.setdefault("models", {})
    providers = models.setdefault("providers", {})

    # Build Spark provider
    # We still validate the models.json source since it's purely internal schema

    spark_source["baseUrl"] = os.getenv("VLLM_GATEWAY_URL", "http://litellm:4000/v1")
    provider_model = SparkProvider.model_validate(spark_source)

    provider_dict = provider_model.model_dump(by_alias=True, exclude_none=True)
    provider_dict["apiKey"] = {
        "source": "env",
        "provider": "default",
        "id": "LITELLM_MASTER_KEY",
    }
    global_max_reserve = 8192
    # Pass through raw values from the registry — no fabrication needed.
    # LiteLLM and the Responses API both default to the model's full capacity
    # when max_tokens is omitted.
    for model in provider_dict.get("models", []):
        max_tokens = model.get("maxTokens")
        if max_tokens:
            global_max_reserve = max(global_max_reserve, max_tokens)

    providers["spark"] = provider_dict

    # Update defaults
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})

    # Sync compaction reserve limit
    compaction = defaults.setdefault("compaction", {})
    compaction["reserveTokens"] = global_max_reserve + 8192

    agent_models = defaults.setdefault("models", {})
    for m in provider_model.models:
        m_id = f"spark/{m.id}"
        if m_id not in agent_models:
            agent_models[m_id] = {}

    # Save back raw JSON, preserving all unstructured fields perfectly
    await asyncio.to_thread(config_path.write_text, json.dumps(config, indent=2) + "\n")
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
