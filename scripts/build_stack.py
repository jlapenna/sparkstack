#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
import copy
import json
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from core.builders.compose import ComposeBuilder
from core.builders.litellm import LiteLLMBuilder
from core.builders.prometheus import PrometheusBuilder
from core.constants import (
    BACKEND_START_PORT,
    BASE_DIR,
    BLACKWELL_MANDATORY_ENV,
    DEFAULT_CONTEXT_WINDOW,
    MAX_DOCKER_MEMORY_GB,
    MAX_VRAM_UTILIZATION,
    REGISTRY_DIR,
    STACKS_DIR,
    USABLE_SPARK_MEMORY_GB,
)
from core.schemas import (
    ComposeData,
    ComposeRegistryModel,
    RegistryModel,
    SparkrunRegistryModel,
)
from core.utils import async_run_command


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


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "_", text.lower()).strip("_")
    return re.sub(r"_+", "_", slug)


class ModelRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.models_path = registry_path / "sparkrun"
        self.base_path = BASE_DIR / "base"

    def load_base_configs(self) -> tuple[dict[str, Any], dict[str, Any]]:
        compose_base_file = self.base_path / "compose-base.yaml"
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
                ["uv", "run", "sparkrun", "recipe", "show", target, "--json"], check=True
            )
            recipe_data = json.loads(result.stdout)

            vram_result = await async_run_command(
                ["uv", "run", "sparkrun", "recipe", "vram", target, "--tp", "1", "--json"],
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
        model_file = self.models_path / f"{model_name}.yaml"

        if model_file.exists():
            with model_file.open("r") as f:
                raw_data = yaml.safe_load(f)
            if "compose" in raw_data:
                return ComposeRegistryModel(
                    identity=model_name,
                    vram_usage=raw_data.get("vram_usage", 0.0),
                    data=ComposeData(compose=raw_data["compose"]),
                )

        recipe_info = await self._get_recipe_info(
            model_name, recipe_path=model_file if model_file.exists() else None
        )
        if recipe_info:
            recipe, vram_est = recipe_info
            return SparkrunRegistryModel(
                identity=model_name,
                recipe=recipe,
                vram_usage=vram_est,
                recipe_path=str(model_file) if model_file.exists() else model_name,
            )

        raise FileNotFoundError(f"Model {model_name} not found in local or public registry.")


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
        else:
            data_dict = model_config.data.model_dump()
            litellm_info = data_dict.get("litellm", {})
            litellm_model = litellm_info.get("litellm_params", {}).get("model", "")
            if litellm_model:
                return litellm_model.replace("openai/", "").replace("hosted_vllm/", "")
            return data_dict.get("benchmark", {}).get("model_id", model_config.identity)


class StackBuilder:
    def __init__(self, stack_name: str, model_args: list[str]):
        self.stack_name = stack_name
        self.requested_models = []
        for arg in model_args:
            overrides = {}
            if ":" in arg:
                arg, overrides_str = arg.split(":", 1)
                for override in overrides_str.split(","):
                    if "=" in override:
                        k, v = override.split("=", 1)
                        overrides[k] = v
            if "=" in arg:
                role, recipe = arg.split("=", 1)
                self.requested_models.append(
                    {"role": role, "recipe": recipe, "overrides": overrides}
                )
            else:
                self.requested_models.append({"role": None, "recipe": arg, "overrides": overrides})

        self.stack_dir = STACKS_DIR / stack_name
        self.registry = ModelRegistry(REGISTRY_DIR)

        self.total_vram = 0.0
        self.total_memory_gb = 0.0
        self.stack_backends = []

    def _get_gateway_ip(self) -> str:
        return "proxy-tier"

    def _inject_blackwell_vars(self, service_cfg: dict[str, Any], role: str | None = None):
        env = {
            item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in service_cfg.get("environment", [])
            if "=" in item
        }
        env.update(
            {
                k: v
                for k, v in BLACKWELL_MANDATORY_ENV.items()
                if k not in env or (k == "VLLM_USE_DEEP_GEMM" and v == "0")
            }
        )
        if role and "OTEL_SERVICE_NAME" not in env:
            env["OTEL_SERVICE_NAME"] = f"vllm-{role}"
        service_cfg["environment"] = [f"{k}={v}" for k, v in env.items()]

    def _parse_memory_gb(self, mem_str: str) -> float:
        match = re.match(r"([\d\.]+)([GgMm])", str(mem_str))
        if not match:
            logger.warning(f"Could not parse memory limit '{mem_str}'. Assuming 32GB.")
            return 32.0
        val, unit = match.groups()
        return float(val) if unit.lower() == "g" else float(val) / 1024.0

    def _check_constraints(self):
        logger.info(
            f"📊 Resource Totals: {self.total_vram * 100:.1f}% VRAM, {self.total_memory_gb:.1f}GB RAM"
        )
        if self.total_vram > MAX_VRAM_UTILIZATION or self.total_memory_gb > MAX_DOCKER_MEMORY_GB:
            logger.error("Resource limits exceeded.")
            logger.warning("Overriding memory limit conservatively.")
        logger.info("✅ Memory Law constraints verified.")

    async def build(self):
        logger.info(f"🏗️  Building stack '{self.stack_name}'...")
        self.stack_dir.mkdir(parents=True, exist_ok=True)
        bench_dir = self.stack_dir / "benchmarks"
        if bench_dir.exists():
            shutil.rmtree(bench_dir)

        base_compose, base_litellm = self.registry.load_base_configs()

        self.compose_builder = ComposeBuilder(self.stack_dir, base_compose)
        self.compose_builder.set_gateway_memory("8G")

        self.litellm_builder = LiteLLMBuilder(self.stack_dir, base_litellm)
        self.prometheus_builder = PrometheusBuilder(self.stack_dir)

        self.port_to_recipe = {}
        self.recipe_to_container = {}

        for idx, req in enumerate(self.requested_models):
            recipe_name = req["recipe"]
            role = req["role"]

            try:
                model_config = await self.registry.load_model(recipe_name)
            except FileNotFoundError as e:
                logger.error(f"Skipping model '{recipe_name}': {e}")
                continue

            # Initialize variables used across both sparkrun and compose paths
            vllm_cfg: dict[str, Any] = {}
            actual_backend_model: str = ""
            human_name: str = model_config.identity.replace(".yaml", "").title()
            context_window: int = DEFAULT_CONTEXT_WINDOW
            model_info: dict[str, Any] = {"input": ["text"]}
            litellm_overrides: dict[str, Any] = {}

            if not role:
                is_embedding = "embedding" in recipe_name.lower() or "bge" in recipe_name.lower()
                if not is_embedding and isinstance(model_config, SparkrunRegistryModel):
                    recipe_dict = model_config.recipe
                    if "--runner pooling" in recipe_dict.get("command", ""):
                        is_embedding = True

                if is_embedding and "embedding" not in self.litellm_builder.added_roles:
                    target_role = "embedding"
                elif "main" not in self.litellm_builder.added_roles:
                    target_role = "main"
                else:
                    target_role = slugify(recipe_name)
            else:
                target_role = role

            routing_ids = [target_role]
            if (
                idx == 0
                and "main" not in routing_ids
                and "main" not in self.litellm_builder.added_roles
            ):
                routing_ids.append("main")

            existing_port = next(
                (p for p, r in self.port_to_recipe.items() if r == recipe_name), None
            )

            if existing_port:
                port = existing_port
                container_hostname = self.recipe_to_container[recipe_name]
                backend_url = f"http://{container_hostname}:{port}/v1"
            else:
                self.total_vram += model_config.vram_usage
                port = BACKEND_START_PORT + len(self.port_to_recipe)
                self.port_to_recipe[port] = recipe_name
                cluster_id = target_role
                container_hostname = f"{cluster_id}_solo"
                self.recipe_to_container[recipe_name] = container_hostname

                if isinstance(model_config, SparkrunRegistryModel):
                    recipe_dict = model_config.recipe
                    backend_url = f"http://{container_hostname}:{port}/v1"
                    prometheus_target = f"{container_hostname}:{port}"

                    vllm_cfg = recipe_dict.get("vllm_config") or recipe_dict.get("defaults") or {}

                    hardware = recipe_dict.get("hardware", {})
                    mem_limit = hardware.get("memory_limit", f"{int(MAX_DOCKER_MEMORY_GB)}G")

                    # Validate Tool Parser Whitelist
                    command_str = recipe_dict.get("command", "")
                    VALID_PARSERS = [
                        "chatml",
                        "hermes",
                        "mistral",
                        "qwen",
                        "qwen3_coder",
                        "llama3_json",
                        "pythonic",
                        "internlm2",
                    ]
                    parser_match = re.search(r"--tool-call-parser\s+(\w+)", command_str)
                    if parser_match:
                        parser_name = parser_match.group(1)
                        if parser_name not in VALID_PARSERS:
                            raise ValueError(
                                f"Invalid tool-call-parser '{parser_name}' in {recipe_name}. Must be one of: {', '.join(VALID_PARSERS)}"
                            )

                    overrides = req.get("overrides", {})
                    if "memory_limit" in overrides:
                        mem_limit = overrides.get("memory_limit")

                    container_img = recipe_dict.get("container", "")
                    if "lmsysorg/sglang" in container_img and "nightly" in container_img:
                        repo = "lmsysorg/sglang"
                        logger.info(f"Resolving latest nightly tag for {repo}...")
                        tag = resolve_latest_image_tag(repo, "cu13")
                        if tag:
                            recipe_dict["container"] = tag
                            vllm_cfg["container"] = tag

                    max_len = int(
                        vllm_cfg.get(
                            "max_model_len", overrides.get("max_model_len", DEFAULT_CONTEXT_WINDOW)
                        )
                    )
                    vllm_cfg["max_model_len"] = str(max_len)

                    if (
                        "gpu_memory_utilization" not in vllm_cfg
                        and "gpu_memory_utilization" not in overrides
                    ):
                        util = min(0.95, model_config.vram_usage)
                        vllm_cfg["gpu_memory_utilization"] = str(util)
                        logger.info(
                            f"Dynamically scaled gpu_memory_utilization to {util} for {recipe_name}"
                        )

                    backend = {
                        "name": target_role,
                        "recipe": f"sparkrun/{Path(model_config.recipe_path).name}",
                        "target": "localhost",
                        "port": port,
                        "env": {},
                        "overrides": {}
                    }
                    if mem_limit:
                        backend["memory_limit"] = mem_limit

                    for k, v in overrides.items():
                        backend["overrides"][k] = v

                    for k, v in recipe_dict.get("env", {}).items():
                        backend["env"][k] = v

                    for k, v in BLACKWELL_MANDATORY_ENV.items():
                        if k not in recipe_dict.get("env", {}):
                            backend["env"][k] = v

                    if "OTEL_SERVICE_NAME" not in recipe_dict.get("env", {}):
                        backend["env"]["OTEL_SERVICE_NAME"] = f"vllm-{target_role}"

                    if "otlp_traces_endpoint" not in recipe_dict.get("defaults", {}):
                        backend["overrides"]["otlp_traces_endpoint"] = "http://otel-collector:4317"

                    if "tensor_parallel_size" not in vllm_cfg and "tensor_parallel" not in vllm_cfg:
                        backend["overrides"]["tensor_parallel"] = "1"

                    for k, v in vllm_cfg.items():
                        if k not in ["port", "served_model_name", "network", "tensor_parallel", "tensor_parallel_size"]:
                            backend["overrides"][k] = v

                    if recipe_dict.get("runtime") == "sglang":
                        backend["overrides"]["attention_backend"] = "triton"
                        backend["overrides"]["enable_metrics"] = "true"
                        backend["overrides"]["mem_fraction_static"] = "0.8"

                    self.stack_backends.append(backend)

                    self.prometheus_builder.add_target(prometheus_target, target_role)

                    actual_backend_model = target_role
                    if isinstance(actual_backend_model, list):
                        actual_backend_model = actual_backend_model[0]

                    human_name = recipe_dict.get(
                        "human_name",
                        recipe_dict.get("name", model_config.identity.replace(".yaml", "").title()),
                    )
                    context_window = int(vllm_cfg.get("max_model_len", DEFAULT_CONTEXT_WINDOW))
                    model_info = {"input": ["text"], "reasoning": False}
                    if "reasoning_parser" in vllm_cfg or "--reasoning-parser" in recipe_dict.get(
                        "command", ""
                    ):
                        model_info["reasoning"] = True

                    litellm_overrides = recipe_dict.get("litellm_overrides", {})

                    logger.info(
                        f"🪄  Orchestrating {recipe_name} via sparkrun (Port: {port}, Mem: {mem_limit})"
                    )
                else:
                    data = model_config.data
                    services = copy.deepcopy(data.compose)
                    container_name = target_role
                    orig_svc_id = list(services.keys())[0]
                    svc_cfg = services.pop(orig_svc_id)
                    svc_cfg["container_name"] = container_name

                    self._inject_blackwell_vars(svc_cfg, role=target_role)
                    svc_cfg.setdefault("labels", []).extend(
                        [f"sparkrun.role={target_role}", "sparkrun.monitoring=true"]
                    )

                    self.compose_builder.add_service(container_name, svc_cfg)
                    backend_url = f"http://{container_name}:8000/v1"
                    self.prometheus_builder.add_target(f"{container_name}:8000", recipe_name)

                    overrides = req.get("overrides", {})
                    mem_limit = overrides.get(
                        "memory_limit",
                        svc_cfg.get("deploy", {})
                        .get("resources", {})
                        .get("limits", {})
                        .get("memory", f"{int(MAX_DOCKER_MEMORY_GB)}G"),
                    )
                    svc_cfg.setdefault("deploy", {}).setdefault("resources", {}).setdefault(
                        "limits", {}
                    )["memory"] = mem_limit
                    self.total_memory_gb += self._parse_memory_gb(mem_limit)

                    data_dict = data.model_dump()
                    human_name = data_dict.get(
                        "human_name", model_config.identity.replace(".yaml", "").title()
                    )
                    litellm_info = data_dict.get("litellm", {})
                    actual_backend_model = (
                        litellm_info.get("litellm_params", {})
                        .get("model", "")
                        .replace("openai/", "")
                        .replace("hosted_vllm/", "")
                    )
                    if not actual_backend_model:
                        actual_backend_model = ModelIDExtractor.extract_model_id(model_config)

                    model_info_map = litellm_info.get("model_info", {})
                    context_window = int(
                        model_info_map.get("context_window", DEFAULT_CONTEXT_WINDOW)
                    )
                    model_info = model_info_map or {"input": ["text"]}

                    litellm_overrides = data_dict.get(
                        "litellm_overrides", litellm_info.get("litellm_params", {})
                    )

                    logger.info(
                        f"📦 Orchestrating {recipe_name} via compose (Container: {container_name}, Mem: {mem_limit})"
                    )

            allowed_overrides = {
                "temperature",
                "frequency_penalty",
                "presence_penalty",
                "repetition_penalty",
                "thinking_format",
            }
            safe_overrides = {k: v for k, v in litellm_overrides.items() if k in allowed_overrides}

            for rid in routing_ids:
                self.litellm_builder.add_model(
                    role_id=rid,
                    backend_model=actual_backend_model,
                    backend_url=backend_url,
                    context_window=context_window,
                    human_name=human_name,
                    model_info=model_info,
                    recipe_name=recipe_name,
                    **safe_overrides,
                )

        self._check_constraints()
        self.compose_builder.write()
        self.litellm_builder.write()
        self.prometheus_builder.write()
        self._generate_launcher_script()
        logger.info(
            f"🚀 Stack '{self.stack_name}' built successfully in spark-stack-registry/stacks/{self.stack_name}"
        )

    def _generate_launcher_script(self):
        stack_yaml = {
            "version": "1",
            "name": self.stack_name,
            "globals": {"network": "proxy-tier"},
            "backends": self.stack_backends,
            "services": {"compose_file": "docker-compose.yaml"}
        }

        stack_yaml_path = self.stack_dir / "stack.yaml"
        with open(stack_yaml_path, "w") as f:
            yaml.dump(stack_yaml, f, sort_keys=False, default_flow_style=False)

        lines = [
            "#!/bin/bash",
            "set -e",
            'CDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
            'PARENT_ENV="${CDIR}/../../.env"',
            "",
            'if [[ ! -f "$PARENT_ENV" ]]; then',
            '  echo "⚠️ Warning: Root .env file not found at $PARENT_ENV, using empty env"',
            '  touch "$PARENT_ENV" || true',
            "fi",
            "set -a",
            'source "$PARENT_ENV" 2>/dev/null || true',
            "set +a",
            "",
            "# Prevent uv from failing if it inherits a relative UV_ENV_FILE from the parent shell",
            "unset UV_ENV_FILE",
            "",
            'uv run python "$CDIR/../../../scripts/launch.py" "$CDIR"'
        ]
        launcher_path = self.stack_dir / "launch.sh"
        launcher_path.write_text("\n".join(lines))
        launcher_path.chmod(0o755)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an AI service stack for NVIDIA Blackwell.")
    parser.add_argument("stack_name", help="Unique name for the stack")
    parser.add_argument("models", nargs="+", help="List of models/aliases")
    args = parser.parse_args()
    asyncio.run(StackBuilder(args.stack_name, args.models).build())
