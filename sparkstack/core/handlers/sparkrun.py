import re
from typing import Any

from loguru import logger

from sparkstack.core.builders.docker import DockerComposeFileBuilder
from sparkstack.core.builders.litellm import LiteLLMBuilder
from sparkstack.core.builders.monitoring import MonitoringBuilder
from sparkstack.core.env import DEFAULT_KV_CACHE_CEILING, MAX_DOCKER_MEMORY_GB
from sparkstack.core.registry import resolve_latest_image_tag
from sparkstack.core.schemas import SparkrunRegistryModel


class SparkrunServiceHandler:
    def __init__(self, model_config: SparkrunRegistryModel, context: dict):
        self.model_config = model_config
        self.context = context
        self.recipe_dict = model_config.recipe
        self.target_role = context["target_role"]
        self.recipe_name = context["recipe_name"]
        self.port = context["port"]
        self.container_hostname = context["container_hostname"]
        self.overrides = context["overrides"]
        self.vllm_env = context["vllm_env"]
        self.blackwell_env = context["blackwell_env"]

    @staticmethod
    def _parse_memory_gb(mem_str: str) -> float:
        """Parse a Docker memory string like '100G' or '512M' into GB."""
        match = re.match(r"([\d\.]+)([GgMm])", mem_str)
        if not match:
            return 32.0
        val, unit = match.groups()
        return float(val) if unit.lower() == "g" else float(val) / 1024.0

    def _validate_recipe(self, command_str: str, vllm_cfg: dict):
        VALID_PARSERS = [
            "chatml",
            "hermes",
            "mistral",
            "qwen",
            "qwen3_coder",
            "qwen3_xml",
            "llama3_json",
            "pythonic",
            "internlm2",
            "gemma4",
        ]
        parser_match = re.search(r"--tool-call-parser\s+(\w+)", command_str)
        if parser_match:
            parser_name = parser_match.group(1)
            if parser_name not in VALID_PARSERS:
                raise ValueError(
                    f"Invalid tool-call-parser '{parser_name}' in {self.recipe_name}. Must be one of: {', '.join(VALID_PARSERS)}"
                )

        INCOMPATIBLE_FLAGS = [
            (
                {"--disable-log-stats"},
                {"VLLM_OTEL_TRACING_ENABLED", "--otlp-traces-endpoint"},
                "Cannot use --disable-log-stats with OTel tracing (req_state.stats will be None)",
            )
        ]
        env_str = str(self.vllm_env) + str(self.blackwell_env)
        for group1, group2, msg in INCOMPATIBLE_FLAGS:
            has_group1 = any(flag in command_str for flag in group1)
            has_group2 = any(flag in command_str or flag in env_str for flag in group2)
            if has_group1 and has_group2:
                raise ValueError(f"Flag incompatibility in {self.recipe_name}: {msg}")

        model_name = vllm_cfg.get("model", "")
        if ("nemotron" in model_name.lower() or "jamba" in model_name.lower()) and (
            "--enforce-eager" not in command_str and not vllm_cfg.get("enforce_eager")
        ):
            logger.warning(
                f"[{self.recipe_name}] Model {model_name} appears to be a hybrid architecture "
                f"but '--enforce-eager' is not set. This may cause Triton JIT compilation crashes on Blackwell."
            )

    def apply_to_builders(
        self,
        docker_builder: DockerComposeFileBuilder,
        gateway_builder: LiteLLMBuilder,
        monitoring_builder: MonitoringBuilder,
    ) -> tuple[float, float, dict[str, Any]]:

        vllm_cfg = self.recipe_dict.get("vllm_config") or self.recipe_dict.get("defaults") or {}
        command_str = self.recipe_dict.get("command", "")

        self._validate_recipe(command_str, vllm_cfg)

        hardware = self.recipe_dict.get("hardware", {})
        mem_limit = self.overrides.get(
            "memory_limit", hardware.get("memory_limit", f"{int(MAX_DOCKER_MEMORY_GB)}G")
        )

        container_img = self.recipe_dict.get("container", "")
        if "lmsysorg/sglang" in container_img and "nightly" in container_img:
            repo = "lmsysorg/sglang"
            logger.info(f"Resolving latest nightly tag for {repo}...")
            tag = resolve_latest_image_tag(repo, "cu13")
            if tag:
                self.recipe_dict["container"] = tag
                vllm_cfg["container"] = tag

        max_len_val = vllm_cfg.get(
            "max_model_len", self.overrides.get("max_model_len", DEFAULT_KV_CACHE_CEILING)
        )
        max_len = int(max_len_val) if max_len_val is not None else DEFAULT_KV_CACHE_CEILING
        vllm_cfg["max_model_len"] = str(max_len)

        if (
            "gpu_memory_utilization" not in vllm_cfg
            and "gpu_memory_utilization" not in self.overrides
        ):
            util = max(0.8, min(0.95, self.model_config.vram_usage))
            vllm_cfg["gpu_memory_utilization"] = str(util)
            logger.info(
                f"Dynamically scaled gpu_memory_utilization to {util} for {self.recipe_name}"
            )

        recipe_out = self.model_config.recipe_path

        backend = {
            "name": self.target_role,
            "recipe": recipe_out,
            "target": "localhost",
            "port": self.port,
            "env": {},
            "overrides": {},
            "labels": [f"sparkrun.role={self.target_role}", "sparkrun.monitoring=true"],
        }
        if mem_limit:
            backend["memory_limit"] = mem_limit

        _ALLOWED_OVERRIDES = {"gpu_memory_utilization"}
        for k, v in self.overrides.items():
            if k in _ALLOWED_OVERRIDES:
                backend["overrides"][k] = v

        for k, v in self.recipe_dict.get("env", {}).items():
            backend["env"][k] = v

        for k, v in self.blackwell_env.items():
            if k not in self.recipe_dict.get("env", {}):
                backend["env"][k] = v

        # Architectural Defaults for Tracing
        # We only inject these if the recipe explicitly enables tracing.
        # This keeps recipes clean while ensuring consistent infrastructure routing.
        tracing_enabled = (
            str(backend["env"].get("VLLM_OTEL_TRACING_ENABLED", "0")) == "1"
            or str(self.recipe_dict.get("env", {}).get("VLLM_OTEL_TRACING_ENABLED", "0")) == "1"
        )

        if tracing_enabled:
            if "OTEL_SERVICE_NAME" not in self.recipe_dict.get("env", {}):
                backend["env"]["OTEL_SERVICE_NAME"] = f"vllm-{self.target_role}"

            backend["env"]["OTEL_TRACES_EXPORTER"] = "otlp"
            backend["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://alloy:4318"
            backend["env"]["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http/protobuf"
            backend["env"]["OTEL_EXPORTER_OTLP_TRACES_PROTOCOL"] = "http/protobuf"
            backend["env"]["OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT"] = "131072"

            if "otlp_traces_endpoint" not in self.recipe_dict.get("defaults", {}):
                backend["overrides"]["otlp_traces_endpoint"] = "http://alloy:4318/v1/traces"

        # Only promote explicitly allowed keys from vllm_cfg into overrides.
        # Recipe defaults should stay in the recipe — sparkrun reads them directly.
        # This prevents stale overrides in stack.yaml when recipes are updated.
        _ALLOWED_VLLM_OVERRIDES = {"gpu_memory_utilization"}
        for k, v in vllm_cfg.items():
            if k in _ALLOWED_VLLM_OVERRIDES:
                backend["overrides"][k] = v

        if self.recipe_dict.get("runtime") == "sglang":
            backend["overrides"]["attention_backend"] = "triton"
            backend["overrides"]["enable_metrics"] = "true"
            backend["overrides"]["mem_fraction_static"] = "0.8"

        monitoring_builder.add_target(
            f"{self.container_hostname}:{self.port}",
            self.target_role,
            instance_name=f"{self.container_hostname}:{self.port}",
        )

        human_name = self.recipe_dict.get(
            "human_name",
            self.recipe_dict.get("name", self.model_config.identity.replace(".yaml", "").title()),
        )

        model_info: dict[str, Any] = {
            "input": ["text"],
            "mode": "chat",
        }
        if "reasoning_parser" in vllm_cfg or "--reasoning-parser" in command_str:
            model_info["supports_reasoning"] = "true"
            model_info["reasoning"] = "true"
        if "--tool-call-parser" in command_str:
            model_info["supports_function_calling"] = "true"

        litellm_overrides = self.recipe_dict.get("litellm_overrides", {})
        thinking_format = litellm_overrides.pop("thinking_format", None)
        if "supports_function_calling" in litellm_overrides:
            model_info["supports_function_calling"] = str(
                litellm_overrides.pop("supports_function_calling")
            ).lower()
        if "supports_reasoning" in litellm_overrides:
            model_info["supports_reasoning"] = str(
                litellm_overrides.pop("supports_reasoning")
            ).lower()
            model_info["reasoning"] = model_info["supports_reasoning"]
        if "reasoning" in litellm_overrides:
            model_info["reasoning"] = str(litellm_overrides.pop("reasoning")).lower()

        for rid in self.context["routing_ids"]:
            gateway_builder.add_model(
                role_id=rid,
                backend_model=self.target_role,
                backend_url=f"http://{self.container_hostname}:{self.port}/v1",
                context_window=max_len,
                human_name=str(human_name) if human_name else "",
                thinking_format=thinking_format,
                model_info=model_info,
                recipe_name=self.recipe_name,
                **litellm_overrides,
            )

        mem_gb = self._parse_memory_gb(mem_limit)
        logger.info(
            f"🪄  Orchestrating {self.recipe_name} via sparkrun (Port: {self.port}, Mem: {mem_limit} [{mem_gb:.1f}GB])"
        )

        return self.model_config.vram_usage, mem_gb, backend
