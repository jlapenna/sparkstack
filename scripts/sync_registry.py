#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3

import asyncio
import json
from pathlib import Path
from loguru import logger
from core.constants import OPENCLAW_CONFIG, PROJECT_ROOT
from core.schemas import SparkProvider


async def sync_registry(
    project_root: Path = PROJECT_ROOT, config_path: Path = OPENCLAW_CONFIG
) -> None:
    logger.info("Syncing models to openclaw.json...")
    models_json = project_root / "current" / "models.json"
    if not models_json.exists():
        logger.warning(f"Source models.json missing at {models_json}")
        return

    source_data = json.loads(models_json.read_text())
    spark_source = source_data.get("spark", {})

    # Load existing config raw
    config = json.loads(config_path.read_text()) if config_path.exists() else {}

    # Update providers
    models = config.setdefault("models", {})
    providers = models.setdefault("providers", {})

    # Build Spark provider
    # We still validate the models.json source since it's purely internal schema
    spark_source["baseUrl"] = "http://vllm-gateway:4000/v1"
    provider_model = SparkProvider.model_validate(spark_source)

    provider_dict = provider_model.model_dump(by_alias=True, exclude_none=True)
    provider_dict["apiKey"] = {
        "source": "env",
        "provider": "default",
        "id": "VLLM_SPARK_API_KEY",
    }
    global_max_reserve = 8192
    # Calculate output buffer sizes (maxTokens) based on the model's actual capacity
    for model in provider_dict.get("models", []):
        ctx_window = model.get("contextWindow", 8192)
        # Allocate 25% of context window for generation, bounded between 2k and 8k tokens
        calc_max = min(8192, max(2048, ctx_window // 4))
        model["maxTokens"] = calc_max
        global_max_reserve = max(global_max_reserve, calc_max)

    providers["spark"] = provider_dict

    # Update defaults
    agents = config.setdefault("agents", {})
    defaults = agents.setdefault("defaults", {})

    # Sync compaction reserve limit across all of OpenClaw so prompts are always truncated
    # enough to not overlap with the largest model's max generation limit (preventing vLLM errors)
    # Plus, add a safety buffer of 8192 tokens to account for tokenizer divergence
    # between OpenClaw's token counting and Gemma-4's actual tokenizer lengths.
    compaction = defaults.setdefault("compaction", {})
    compaction["reserveTokens"] = global_max_reserve + 8192

    agent_models = defaults.setdefault("models", {})
    for m in provider_model.models:
        m_id = f"spark/{m.id}"

        if m_id not in agent_models:
            agent_models[m_id] = {}

    # Save back raw JSON, preserving all unstructured fields perfectly
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    logger.info("openclaw.json synchronized correctly.")


if __name__ == "__main__":
    asyncio.run(sync_registry())
