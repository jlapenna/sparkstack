import os
from pathlib import Path

import yaml

from core.schemas import (
    LiteLLMConfig,
    LiteLLMModelEntry,
    LiteLLMModelInfo,
    LiteLLMParams,
    ModelsConfig,
    OpenClawModel,
    OpenClawModelCompat,
    SparkProvider,
)


class LiteLLMBuilder:
    def __init__(self, stack_dir: Path, litellm_base: dict):
        self.stack_dir = stack_dir
        self.litellm_config = LiteLLMConfig()
        self.litellm_config.litellm_settings = litellm_base.get("litellm_settings", {})
        if "model_alias_map" not in self.litellm_config.litellm_settings:
            self.litellm_config.litellm_settings["model_alias_map"] = {}
        self.litellm_config.general_settings = litellm_base.get("general_settings", {})
        self.litellm_config.router_settings = litellm_base.get("router_settings", {})

        self.models_json = ModelsConfig(
            spark=SparkProvider(api_key=os.environ.get("VLLM_SPARK_API_KEY", ""))
        )
        self.added_roles = set()

    def add_model(
        self,
        role_id: str,
        backend_model: str,
        backend_url: str,
        context_window: int,
        human_name: str,
        model_info: dict,
        recipe_name: str = "",
        temperature: float | None = None,
        frequency_penalty: float | None = None,
        presence_penalty: float | None = None,
        repetition_penalty: float | None = None,
        thinking_format: str | None = None,
    ):
        if role_id in self.added_roles:
            return

        cwin = context_window
        params = {
            "model": f"openai/{backend_model}",
            "api_base": backend_url,
            "role_map": {"developer": "system"} if "embedding" not in role_id.lower() else None,
        }
        if "embedding" in role_id.lower():
            params["encoding_format"] = "float"
        else:
            pass

        if temperature is not None:
            params["temperature"] = temperature
        if frequency_penalty is not None:
            params["frequency_penalty"] = frequency_penalty
        if presence_penalty is not None:
            params["presence_penalty"] = presence_penalty
        if repetition_penalty is not None:
            params["extra_body"] = {"repetition_penalty": repetition_penalty}

        self.litellm_config.model_list.append(
            LiteLLMModelEntry(
                model_name=role_id,
                litellm_params=LiteLLMParams(**params),
                model_info=LiteLLMModelInfo(
                    context_window=cwin, max_tokens=cwin, base_model=recipe_name or backend_model
                ),
            )
        )
        
        self.litellm_config.litellm_settings["model_alias_map"][f"spark/{role_id}"] = role_id

        display_name = (
            f"Spark Main ({human_name})"
            if role_id == "main"
            else f"{role_id.title()} ({human_name})"
        )
        model_entry = OpenClawModel(
            id=role_id,
            name=display_name,
            context_window=cwin,
            max_tokens=cwin,
            input=model_info.get("input", ["text"]),
            reasoning=model_info.get("reasoning"),
        )
        if model_info.get("reasoning"):
            # Explicit thinking_format from recipe wins, otherwise default to openai
            resolved_format = thinking_format or "openai"
            model_entry.compat = OpenClawModelCompat(thinking_format=resolved_format)

        self.models_json.spark.models.append(model_entry)
        self.added_roles.add(role_id)

    def write(self):
        with (self.stack_dir / "litellm-config.yaml").open("w") as f:
            yaml.dump(self.litellm_config.model_dump(exclude_none=True), f, sort_keys=False)
        with (self.stack_dir / "models.json").open("w") as f:
            f.write(self.models_json.model_dump_json(indent=2, by_alias=True))
