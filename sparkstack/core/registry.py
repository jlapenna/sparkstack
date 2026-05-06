import json
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from sparkstack.core.env import BASE_DIR, SPARKRUN_CMD, USABLE_SPARK_MEMORY_GB
from sparkstack.core.schemas import (
    ComposeData,
    ComposeRegistryModel,
    RegistryModel,
    SparkrunRegistryModel,
)
from sparkstack.core.utils import async_run_command


def resolve_latest_image_tag(repo: str, filter_string: str = "cu13") -> str | None:
    url = f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=20"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode("utf-8"))
            tags = [r["name"] for r in data.get("results", []) if filter_string in r["name"]]
            if tags:
                return f"{repo}:{tags[0]}"
    except Exception as e:
        logger.warning(f"Failed to fetch latest tag for {repo}: {e}")
    return None


class ModelRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.models_path = registry_path / "sparkrun"
        self.base_path = BASE_DIR / "litellm"

    def load_base_configs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        compose_base_file = self.base_path / "compose-litellm.yaml"
        litellm_settings_file = self.base_path / "litellm-settings.yaml"

        with compose_base_file.open("r") as f:
            compose_config = yaml.safe_load(f)
        with litellm_settings_file.open("r") as f:
            litellm_config = yaml.safe_load(f)
        return compose_config, litellm_config

    async def _get_recipe_info(
        self, model_name: str, recipe_path: Path | None = None
    ) -> tuple[dict, float] | None:
        target = str(recipe_path) if recipe_path else model_name
        try:
            result = await async_run_command(
                [*SPARKRUN_CMD, "recipe", "show", target, "--json"], check=True
            )
            recipe_data = json.loads(result.stdout)

            vram_result = await async_run_command(
                [*SPARKRUN_CMD, "recipe", "vram", target, "--tp", "1", "--json"],
                check=False,
            )
            if vram_result.returncode == 0:
                vram_data = json.loads(vram_result.stdout)
                vram_gb = vram_data.get("usable_gpu_memory_gb") or vram_data.get(
                    "total_per_gpu_gb", 0.0
                )
            else:
                logger.warning(f"VRAM estimation failed for {model_name}, using 0.0")
                vram_gb = 0.0

            return recipe_data, vram_gb / USABLE_SPARK_MEMORY_GB
        except Exception as e:
            logger.debug(f"Failed to get recipe info for {model_name}: {e}")
            return None

    async def load_model(self, model_name: str) -> RegistryModel:
        """Load a model by identity.

        Accepts bare names (``gemma-4-31b-nvfp4``) or canonical registry
        paths (``sparkrun/gemma-4-31b-nvfp4.yaml``).  Normalisation happens
        here so callers never need to strip or re-add prefixes.
        """
        bare_name = model_name.removeprefix("sparkrun/").removesuffix(".yaml")
        model_file = self.models_path / f"{bare_name}.yaml"

        canonical_path = bare_name if bare_name.startswith("@") else f"sparkrun/{bare_name}.yaml"

        if model_file.exists():
            with model_file.open("r") as f:
                raw_data = yaml.safe_load(f)
            if "compose" in raw_data:
                return ComposeRegistryModel(
                    identity=bare_name,
                    vram_usage=raw_data.get("vram_usage", 0.0),
                    data=ComposeData(compose=raw_data["compose"]),
                )

        recipe_info = await self._get_recipe_info(
            bare_name, recipe_path=model_file if model_file.exists() else None
        )
        if recipe_info:
            recipe, vram_est = recipe_info
            return SparkrunRegistryModel(
                identity=bare_name,
                recipe=recipe,
                vram_usage=vram_est,
                recipe_path=canonical_path,
            )

        raise FileNotFoundError(f"Model {bare_name} not found in local or public registry.")


class ModelIDExtractor:
    @staticmethod
    def extract_model_id(model_config: RegistryModel) -> str:
        if isinstance(model_config, SparkrunRegistryModel):
            recipe_dict = model_config.recipe
            vllm_cfg = recipe_dict.get("vllm_config")
            if not vllm_cfg:
                vllm_cfg = recipe_dict.get("defaults", {})

            served = vllm_cfg.get(
                "served_model_name", recipe_dict.get("model") or model_config.identity
            )
            return served[0] if isinstance(served, list) else served
        data_dict = model_config.data.model_dump()
        litellm_info = data_dict.get("litellm", {})
        litellm_model = litellm_info.get("litellm_params", {}).get("model", "")
        if litellm_model:
            return litellm_model.replace("openai/", "").replace("hosted_vllm/", "")
        return data_dict.get("benchmark", {}).get("model_id", model_config.identity)
