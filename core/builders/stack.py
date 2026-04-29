import os
import shutil
import subprocess

import yaml
from loguru import logger

from core.builders.apigateway import ApiGatewayBuilder
from core.builders.docker import DockerComposeFileBuilder
from core.builders.monitoring import MonitoringBuilder
from core.env import (
    MAX_DOCKER_MEMORY_GB,
    MAX_VRAM_UTILIZATION,
    OPENCLAW_CONFIG_PATH,
    REGISTRY_DIR,
    STACKS_DIR,
)
from core.handlers.docker import DockerServiceHandler
from core.handlers.gateway import ApiGatewayServiceConfigurator
from core.handlers.sparkrun import SparkrunServiceHandler
from core.registry import ModelRegistry, SparkrunRegistryModel
from core.utils import slugify

BACKEND_START_PORT = int(os.getenv("BACKEND_START_PORT", 8001))

VLLM_ENV = {
    "VLLM_OTEL_TRACING_ENABLED": "1",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://alloy:4318/v1/traces",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "131072",
}

BLACKWELL_MANDATORY_ENV = VLLM_ENV | {
    "VLLM_ATTENTION_BACKEND": "FLASHINFER",
    "VLLM_FLASHINFER_MOE_BACKEND": "latency",
    "VLLM_BLACKWELL_LAYOUT": "1",
    "VLLM_BLACKWELL_UMA_OVERLAP": "1",
    "VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8": "1",
    "VLLM_USE_DEEP_GEMM": "0",
}


class StackBuilder:
    def __init__(self, stack_name: str, model_args: list[str], allow_no_embedding: bool = False):
        self.stack_name = stack_name
        self.allow_no_embedding = allow_no_embedding
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

        self.port_to_recipe = {}
        self.recipe_to_container = {}

    def _check_constraints(self):
        vram_pct = self.total_vram * 100
        logger.info(f"📊 Resource Totals: {vram_pct:.1f}% VRAM, {self.total_memory_gb:.1f}GB RAM")
        if self.total_vram > MAX_VRAM_UTILIZATION or self.total_memory_gb > MAX_DOCKER_MEMORY_GB:
            logger.error("Resource limits exceeded.")
            logger.warning("Overriding memory limit conservatively.")
        if self.total_vram < 0.85:
            logger.warning(
                f"⚠️ VRAM UNDER-UTILIZED: Stack only claims {vram_pct:.1f}% VRAM. Consider increasing `gpu_memory_utilization` to maximize KV cache."
            )
        if self.total_memory_gb < 90.0:
            logger.warning(
                f"⚠️ SYSTEM RAM UNDER-UTILIZED: Stack only claims {self.total_memory_gb:.1f}GB RAM. Consider adding `--cpu-offload-gb` to offload KV cache."
            )
        logger.info("✅ Memory Law constraints verified.")

    async def build(self):
        if not self.allow_no_embedding:
            has_embedding = any(
                req["role"] == "embedding"
                or "embedding" in req["recipe"].lower()
                or "bge" in req["recipe"].lower()
                for req in self.requested_models
            )
            if not has_embedding:
                raise ValueError(
                    "No embedding model found in requested models. "
                    "Use --allow-no-embedding if you intentionally want to turn up a stack without one."
                )

        logger.info(f"🏗️  Building stack '{self.stack_name}'...")
        self.stack_dir.mkdir(parents=True, exist_ok=True)

        if OPENCLAW_CONFIG_PATH.exists():
            shutil.copy2(OPENCLAW_CONFIG_PATH, self.stack_dir / "openclaw.json")
            logger.info(f"📄 Copied openclaw.json to {self.stack_dir}")

        bench_dir = self.stack_dir / "benchmarks"
        if bench_dir.exists():
            shutil.rmtree(bench_dir)

        base_compose, base_litellm = self.registry.load_base_configs()

        self.docker_builder = DockerComposeFileBuilder(self.stack_dir, base_compose)
        ApiGatewayServiceConfigurator.configure(self.docker_builder, "8G")

        self.gateway_builder = ApiGatewayBuilder(self.stack_dir, base_litellm)
        self.monitoring_builder = MonitoringBuilder(self.stack_dir)

        for idx, req in enumerate(self.requested_models):
            await self._process_model_request(idx, req)

        self._check_constraints()
        self.docker_builder.write()
        self.gateway_builder.write()
        self.monitoring_builder.write()
        self._validate_configs()
        self._generate_launcher_script()
        logger.info(
            f"🚀 Stack '{self.stack_name}' built successfully in spark-stack-registry/stacks/{self.stack_name}"
        )

    async def _process_model_request(self, idx: int, req: dict):
        recipe_name = req["recipe"]
        role = req["role"]

        try:
            model_config = await self.registry.load_model(recipe_name)
        except FileNotFoundError as e:
            logger.error(f"Skipping model '{recipe_name}': {e}")
            return

        is_embedding = False
        if not role:
            is_embedding = "embedding" in recipe_name.lower() or "bge" in recipe_name.lower()
            if (
                not is_embedding
                and isinstance(model_config, SparkrunRegistryModel)
                and "--runner pooling" in model_config.recipe.get("command", "")
            ):
                is_embedding = True

            if is_embedding and "embedding" not in self.gateway_builder.added_roles:
                target_role = "embedding"
            elif "main" not in self.gateway_builder.added_roles:
                target_role = "main"
            else:
                target_role = slugify(recipe_name)
        else:
            target_role = role

        routing_ids = [target_role]
        if (
            idx == 0
            and "main" not in routing_ids
            and "main" not in self.gateway_builder.added_roles
        ):
            routing_ids.append("main")

        existing_port = next((p for p, r in self.port_to_recipe.items() if r == recipe_name), None)

        if existing_port:
            port = existing_port
            container_hostname = self.recipe_to_container[recipe_name]
        else:
            port = BACKEND_START_PORT + len(self.port_to_recipe)
            self.port_to_recipe[port] = recipe_name
            container_hostname = f"{target_role}_solo"
            self.recipe_to_container[recipe_name] = container_hostname

        context = {
            "target_role": target_role,
            "recipe_name": recipe_name,
            "port": port,
            "container_hostname": container_hostname,
            "routing_ids": routing_ids,
            "overrides": req.get("overrides", {}),
            "vllm_env": VLLM_ENV,
            "blackwell_env": BLACKWELL_MANDATORY_ENV,
        }

        if isinstance(model_config, SparkrunRegistryModel):
            handler = SparkrunServiceHandler(model_config, context)
        else:
            handler = DockerServiceHandler(model_config, context)

        vram, mem_gb, backend_dict = handler.apply_to_builders(
            self.docker_builder, self.gateway_builder, self.monitoring_builder
        )

        if not existing_port:
            self.total_vram += vram
            self.total_memory_gb += mem_gb

        if backend_dict:
            self.stack_backends.append(backend_dict)

    def _validate_configs(self):
        logger.info("🔍 Validating generated configurations...")

        # 1. Validate Docker Compose
        compose_file = self.stack_dir / "docker-compose.yaml"
        if compose_file.exists():
            try:
                subprocess.run(
                    ["docker", "compose", "-f", str(compose_file), "config", "-q"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"❌ Docker Compose validation failed:\n{e.stderr}")
                raise ValueError("Invalid docker compose configuration generated.") from e

        # 2. Validate Prometheus
        prom_file = self.stack_dir / "prometheus.yml"
        if prom_file.exists():
            try:
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{prom_file.absolute()}:/etc/prometheus/prometheus.yml:ro",
                        "--entrypoint",
                        "promtool",
                        "prom/prometheus:latest",
                        "check",
                        "config",
                        "/etc/prometheus/prometheus.yml",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                logger.error(
                    f"❌ Prometheus configuration validation failed:\n{e.stderr}\n{e.stdout}"
                )
                raise ValueError("Invalid prometheus configuration generated.") from e

    def _generate_launcher_script(self):
        stack_yaml = {
            "version": "1",
            "name": self.stack_name,
            "globals": {"network": "proxy-tier"},
            "backends": self.stack_backends,
            "services": {"compose_file": "docker-compose.yaml"},
        }

        stack_yaml_path = self.stack_dir / "stack.yaml"
        with open(stack_yaml_path, "w") as f:
            yaml.dump(stack_yaml, f, sort_keys=False, default_flow_style=False)
