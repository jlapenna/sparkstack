"""Regression test: agent-level models.json must stay consistent with the global openclaw.json.

OpenClaw auto-generates per-agent ``models.json`` files that take precedence
over the global ``openclaw.json`` config.  ``sync_registry.py`` only writes to
the global config, so agent-level files can silently drift.  A missing or stale
``maxTokens`` triggers a 16-token OpenAI default fallback that truncates
reasoning models — the exact root cause of the 2026-04-29T15:25 incident.

This test ensures that every agent-level ``models.json`` containing a ``spark``
provider has model entries whose ``maxTokens`` and ``contextWindow`` match the
global config.
"""

import json
from pathlib import Path

import pytest
from loguru import logger

from core.env import OPENCLAW_CONFIG_DIR, OPENCLAW_CONFIG_PATH


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _spark_models_by_id(config: dict) -> dict[str, dict]:
    """Extract spark provider models keyed by model id."""
    providers = config.get("models", config).get("providers", {})
    spark = providers.get("spark", {})
    models = spark.get("models", [])
    return {m["id"]: m for m in models if "id" in m}


@pytest.mark.order(2)
def test_agent_models_maxTokens_matches_global():
    """Every agent-level spark model must carry a maxTokens value consistent
    with the global openclaw.json config.

    Drift here silently triggers a 16-token completion limit for the affected
    agent, causing reasoning truncation and payloads=0 failures.
    """
    if not OPENCLAW_CONFIG_PATH.exists():
        pytest.skip("openclaw.json not found — OpenClaw not configured")

    global_config = _load_json(OPENCLAW_CONFIG_PATH)
    global_spark_models = _spark_models_by_id(global_config)

    if not global_spark_models:
        pytest.skip("No spark provider configured in global openclaw.json")

    agents_dir = OPENCLAW_CONFIG_DIR / "agents"
    if not agents_dir.is_dir():
        pytest.skip("No agents directory found")

    agent_model_files = sorted(agents_dir.glob("*/agent/models.json"))
    if not agent_model_files:
        pytest.skip("No agent-level models.json files found")

    drift_errors: list[str] = []

    for agent_models_path in agent_model_files:
        agent_name = agent_models_path.parent.parent.name
        try:
            agent_config = _load_json(agent_models_path)
        except (json.JSONDecodeError, OSError) as exc:
            drift_errors.append(f"{agent_name}: failed to read models.json: {exc}")
            continue

        agent_spark_models = _spark_models_by_id(agent_config)
        if not agent_spark_models:
            logger.debug(f"  {agent_name}: no spark provider — skipping")
            continue

        for model_id, global_model in global_spark_models.items():
            agent_model = agent_spark_models.get(model_id)
            if agent_model is None:
                continue

            global_max = global_model.get("maxTokens")
            agent_max = agent_model.get("maxTokens")

            # Critical: agent must have maxTokens if global does
            if global_max is not None and agent_max is None:
                drift_errors.append(
                    f"{agent_name}/spark/{model_id}: maxTokens MISSING "
                    f"(global={global_max}). "
                    f"Will fall back to 16-token OpenAI default."
                )
            elif global_max is not None and agent_max != global_max:
                drift_errors.append(
                    f"{agent_name}/spark/{model_id}: maxTokens MISMATCH "
                    f"(agent={agent_max}, global={global_max})"
                )

            global_ctx = global_model.get("contextWindow")
            agent_ctx = agent_model.get("contextWindow")
            if global_ctx is not None and agent_ctx is not None and agent_ctx != global_ctx:
                drift_errors.append(
                    f"{agent_name}/spark/{model_id}: contextWindow MISMATCH "
                    f"(agent={agent_ctx}, global={global_ctx})"
                )

        logger.info(f"  ✅ {agent_name}: spark provider consistent with global config")

    if drift_errors:
        for err in drift_errors:
            logger.error(f"  ❌ {err}")
        pytest.fail(
            f"Agent-level config drift detected in {len(drift_errors)} model(s):\n"
            + "\n".join(f"  • {e}" for e in drift_errors)
        )

    logger.info(
        f"✅ Pass: All {len(agent_model_files)} agent model configs "
        f"consistent with global openclaw.json"
    )
