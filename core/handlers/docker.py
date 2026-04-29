import copy
import re
from typing import Any

from loguru import logger

from core.builders.apigateway import ApiGatewayBuilder
from core.builders.docker import DockerComposeFileBuilder
from core.builders.monitoring import MonitoringBuilder
from core.env import DEFAULT_CONTEXT_WINDOW, MAX_DOCKER_MEMORY_GB
from core.registry import ModelIDExtractor
from core.schemas import ComposeRegistryModel


class DockerServiceHandler:
    def __init__(self, model_config: ComposeRegistryModel, context: dict):
        self.model_config = model_config
        self.context = context
        self.target_role = context["target_role"]
        self.recipe_name = context["recipe_name"]
        self.overrides = context["overrides"]
        self.blackwell_env = context["blackwell_env"]

    def _parse_memory_gb(self, mem_str: str) -> float:
        match = re.match(r"([\d\.]+)([GgMm])", str(mem_str))
        if not match:
            return 32.0
        val, unit = match.groups()
        return float(val) if unit.lower() == "g" else float(val) / 1024.0

    def _inject_blackwell_vars(self, service_cfg: dict[str, Any], role: str | None = None):
        env = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in service_cfg.get("environment", [])
            if "=" in item
        }
        env.update(
            {
                k: v
                for k, v in self.blackwell_env.items()
                if k not in env or (k == "VLLM_USE_DEEP_GEMM" and v == "0")
            }
        )
        if role and "OTEL_SERVICE_NAME" not in env:
            env["OTEL_SERVICE_NAME"] = f"vllm-{role}"
        service_cfg["environment"] = [f"{k}={v}" for k, v in env.items()]

    def apply_to_builders(
        self,
        docker_builder: DockerComposeFileBuilder,
        gateway_builder: ApiGatewayBuilder,
        monitoring_builder: MonitoringBuilder,
    ) -> tuple[float, float, dict[str, Any] | None]:

        data = self.model_config.data
        services = copy.deepcopy(data.compose)
        container_name = self.target_role
        orig_svc_id = list(services.keys())[0]
        svc_cfg = services.pop(orig_svc_id)
        svc_cfg["container_name"] = container_name

        self._inject_blackwell_vars(svc_cfg, role=self.target_role)
        svc_cfg.setdefault("labels", []).extend(
            [f"sparkrun.role={self.target_role}", "sparkrun.monitoring=true"]
        )

        docker_builder.add_service(container_name, svc_cfg)
        backend_url = f"http://{container_name}:8000/v1"
        monitoring_builder.add_target(f"{container_name}:8000", self.recipe_name)

        mem_limit = self.overrides.get(
            "memory_limit",
            svc_cfg.get("deploy", {})
            .get("resources", {})
            .get("limits", {})
            .get("memory", f"{int(MAX_DOCKER_MEMORY_GB)}G"),
        )
        svc_cfg.setdefault("deploy", {}).setdefault("resources", {}).setdefault("limits", {})[
            "memory"
        ] = mem_limit
        mem_gb = self._parse_memory_gb(mem_limit)

        data_dict = data.model_dump()
        human_name = data_dict.get(
            "human_name", self.model_config.identity.replace(".yaml", "").title()
        )

        litellm_info = data_dict.get("litellm", {})
        actual_backend_model = (
            litellm_info.get("litellm_params", {})
            .get("model", "")
            .replace("openai/", "")
            .replace("hosted_vllm/", "")
        )
        if not actual_backend_model:
            actual_backend_model = ModelIDExtractor.extract_model_id(self.model_config)

        model_info_map = litellm_info.get("model_info", {})
        context_window = int(model_info_map.get("context_window", DEFAULT_CONTEXT_WINDOW))
        model_info = model_info_map or {"input": ["text"]}

        litellm_overrides = data_dict.get(
            "litellm_overrides", litellm_info.get("litellm_params", {})
        )

        if "supports_function_calling" in litellm_overrides:
            model_info["supports_function_calling"] = litellm_overrides.pop(
                "supports_function_calling"
            )

        for rid in self.context["routing_ids"]:
            gateway_builder.add_model(
                role_id=rid,
                backend_model=actual_backend_model,
                backend_url=backend_url,
                context_window=context_window,
                human_name=human_name,
                thinking_format=litellm_overrides.pop("thinking_format", None),
                model_info=model_info,
                recipe_name=self.recipe_name,
                **litellm_overrides,
            )

        logger.info(
            f"📦 Orchestrating {self.recipe_name} via compose (Container: {container_name}, Mem: {mem_limit})"
        )

        return 0.0, mem_gb, None  # No stack.yaml backend entry for pure compose services
