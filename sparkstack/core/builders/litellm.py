from pathlib import Path

import yaml

from sparkstack.core.schemas import (
    LiteLLMConfig,
    LiteLLMModelEntry,
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

        self.models_json = ModelsConfig(spark=SparkProvider(api_key="${LITELLM_MASTER_KEY}"))
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
        thinking_format: str | None = None,
        **litellm_kwargs,
    ):
        if role_id in self.added_roles:
            return

        cwin = model_info.get("context_window", context_window)

        # Check all possible indicators of a reasoning model
        is_reasoning = (
            model_info.get("reasoning", False)
            or model_info.get("supports_reasoning", False)
            or (thinking_format is not None)
        )

        # --- LiteLLM litellm_params ---
        # role_map is NOT set here — the global litellm_setting
        # `openai_developer_role_to_system: true` handles developer→system
        # mapping for all models.
        params = {
            "model": f"openai/{backend_model}",
            "api_base": backend_url,
        }
        if "embedding" in role_id.lower():
            params["encoding_format"] = "float"

        # Apply any litellm_kwargs directly to params (e.g., presence_penalty)
        for k, v in litellm_kwargs.items():
            params[k] = v

        # --- LiteLLM model_info ---
        # Only fields LiteLLM actually consumes: context_window, base_model,
        # mode, supports_function_calling, supports_reasoning.
        # NOT max_tokens (LiteLLM defaults to model capacity), NOT input
        # (OpenClaw-only field).
        minfo = {
            "context_window": cwin,
            "base_model": recipe_name or backend_model,
        }
        if "mode" in model_info:
            minfo["mode"] = model_info["mode"]
        if "supports_function_calling" in model_info:
            minfo["supports_function_calling"] = model_info["supports_function_calling"]
        if is_reasoning:
            minfo["supports_reasoning"] = True

        if "api_key" not in params:
            params["api_key"] = "${LITELLM_MASTER_KEY:-}"

        self.litellm_config.model_list.append(
            LiteLLMModelEntry(
                model_name=role_id,
                litellm_params=params,
                model_info=minfo,
            )
        )

        self.litellm_config.litellm_settings["model_alias_map"][f"spark/{role_id}"] = role_id

        display_name = (
            f"Spark Main ({human_name})"
            if role_id == "main"
            else f"{role_id.title()} ({human_name})"
        )

        # max_tokens: per-turn completion budget.  Pass through from registry;
        # fall back to context_window if absent (OpenClawModel's validator will
        # clamp unsafe values).
        max_tokens = model_info.get("max_tokens", cwin)

        model_entry = OpenClawModel(
            id=role_id,
            name=display_name,
            context_window=cwin,
            max_tokens=max_tokens,
            input=model_info.get("input", ["text"]),
            reasoning=is_reasoning,
            api=model_info.get("api", "openai-responses"),
        )

        # --- Compat flags ---
        # Only set fields the registry explicitly provides. Field names match
        # OpenClaw's ModelCompatConfig (camelCase via alias_generator):
        #   supports_tools → supportsTools
        #   supports_prompt_cache_key → supportsPromptCacheKey
        #   supports_store → supportsStore
        #   supports_developer_role → supportsDeveloperRole
        compat_kwargs = {}
        if model_info.get("reasoning") or is_reasoning:
            compat_kwargs["thinking_format"] = thinking_format or "openai"
        if "supports_function_calling" in model_info:
            compat_kwargs["supports_tools"] = model_info["supports_function_calling"]
        if "supports_prompt_cache_key" in model_info:
            compat_kwargs["supports_prompt_cache_key"] = model_info["supports_prompt_cache_key"]
        if "supports_store" in model_info:
            compat_kwargs["supports_store"] = model_info["supports_store"]
        if "supports_developer_role" in model_info:
            compat_kwargs["supports_developer_role"] = model_info["supports_developer_role"]
        if "supports_reasoning_effort" in model_info:
            compat_kwargs["supports_reasoning_effort"] = model_info["supports_reasoning_effort"]
        if "max_tokens_field" in model_info:
            compat_kwargs["max_tokens_field"] = model_info["max_tokens_field"]
        if compat_kwargs:
            model_entry.compat = OpenClawModelCompat(**compat_kwargs)

        self.models_json.spark.models.append(model_entry)
        self.added_roles.add(role_id)

    def write(self):
        with (self.stack_dir / "litellm-config.yaml").open("w") as f:
            yaml.dump(self.litellm_config.model_dump(exclude_none=True), f, sort_keys=False)
        with (self.stack_dir / "models.json").open("w") as f:
            f.write(self.models_json.model_dump_json(indent=2, by_alias=True))
