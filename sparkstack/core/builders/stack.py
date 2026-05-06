import shutil
import subprocess
from pathlib import Path

import yaml
from loguru import logger

from sparkstack.core.builders.docker import DockerComposeFileBuilder
from sparkstack.core.builders.litellm import LiteLLMBuilder
from sparkstack.core.builders.monitoring import MonitoringBuilder
from sparkstack.core.env import (
    BACKEND_START_PORT,
    BLACKWELL_MANDATORY_ENV,
    MAX_DOCKER_MEMORY_GB,
    MAX_VRAM_UTILIZATION,
    OPENCLAW_CONFIG_PATH,
    REGISTRY_DIR,
    STACKS_DIR,
    SYSTEM_RESERVED_MEMORY_GB,
    USABLE_SPARK_MEMORY_GB,
    VLLM_ENV,
)
from sparkstack.core.handlers.docker import DockerServiceHandler
from sparkstack.core.handlers.gateway import ApiGatewayServiceConfigurator
from sparkstack.core.handlers.sparkrun import SparkrunServiceHandler
from sparkstack.core.registry import ModelRegistry, SparkrunRegistryModel
from sparkstack.core.schemas import ModelRequest
from sparkstack.core.utils.strings import slugify


class StackBuilder:
    @classmethod
    async def rebuild_from_stack(cls, stack_dir: Path) -> None:
        """Re-run the full config generation pipeline from an existing stack.yaml.

        Always regenerates litellm-config.yaml, models.json, prometheus.yml,
        docker-compose.yaml, and stack.yaml. Called by update_services to ensure
        builder code changes take effect and to sanitize configurations.
        """
        stack_yaml_path = stack_dir / "stack.yaml"
        if not stack_yaml_path.exists():
            raise FileNotFoundError(f"No stack.yaml found in {stack_dir}")

        with open(stack_yaml_path) as f:
            stack = yaml.safe_load(f)

        # Construct ModelRequest objects from the full backend stanzas,
        # preserving memory_limit, env overrides, and other fields that
        # handlers need for accurate resource accounting.
        requests = []
        _ALLOWED_OVERRIDES = {"gpu_memory_utilization"}

        for backend in stack.get("backends", []):
            overrides = dict(backend.get("overrides", {}))

            # Promote backend-level fields into overrides so handlers see them.
            if "memory_limit" in backend:
                overrides["memory_limit"] = backend["memory_limit"]

            # Sanitize overrides to prevent redefining recipe properties
            overrides = {
                k: v for k, v in overrides.items() if k in _ALLOWED_OVERRIDES or k == "memory_limit"
            }

            requests.append(
                ModelRequest(
                    role=backend["name"],
                    recipe=backend["recipe"],
                    overrides=overrides,
                )
            )

        stack_name = stack_dir.name
        builder = cls(stack_name, requests, allow_no_embedding=True)
        # Override stack_dir to match the actual location (may differ from
        # STACKS_DIR / stack_name when using the 'current' symlink).
        builder.stack_dir = stack_dir.resolve()
        builder._rebuilding = True
        await builder.build()
        logger.info(f"🔄 Configs rebuilt from {stack_yaml_path}")

    def __init__(
        self,
        stack_name: str,
        model_requests: list[ModelRequest],
        allow_no_embedding: bool = False,
    ):
        self.stack_name = stack_name
        self.allow_no_embedding = allow_no_embedding
        self._rebuilding = False
        self.requested_models = model_requests

        self.stack_dir = STACKS_DIR / stack_name
        self.registry = ModelRegistry(REGISTRY_DIR)

        self.total_vram = 0.0
        self.total_memory_gb = 0.0
        self.stack_backends = []

        self.port_to_recipe = {}
        self.recipe_to_container = {}

    # Fixed overhead for monitoring/gateway containers not tracked by handlers.
    # Prometheus (2G) + Grafana (0.5G) + Alloy (0.5G) + Tempo (1G) + misc (1G).
    _MONITORING_OVERHEAD_GB = 5.0

    def _check_constraints(self):
        vram_pct = self.total_vram * 100
        total_declared = self.total_memory_gb + self._MONITORING_OVERHEAD_GB
        logger.info(
            f"📊 Resource Budget:\n"
            f"   VRAM: {vram_pct:.1f}% (ceiling: {MAX_VRAM_UTILIZATION * 100:.0f}%)\n"
            f"   RAM (backends): {self.total_memory_gb:.1f}GB\n"
            f"   RAM (monitoring overhead): {self._MONITORING_OVERHEAD_GB:.1f}GB\n"
            f"   RAM (total declared): {total_declared:.1f}GB\n"
            f"   RAM ceiling: {MAX_DOCKER_MEMORY_GB:.1f}GB "
            f"({USABLE_SPARK_MEMORY_GB:.0f}GB usable - {SYSTEM_RESERVED_MEMORY_GB:.0f}GB system reserve)"
        )

        if total_declared > MAX_DOCKER_MEMORY_GB:
            raise ValueError(
                f"Total declared memory ({total_declared:.1f}GB) exceeds "
                f"MAX_DOCKER_MEMORY_GB ({MAX_DOCKER_MEMORY_GB:.1f}GB). "
                f"Reduce backend memory_limit values or lower SYSTEM_RESERVED_MEMORY_GB."
            )

        # Small tolerance for IEEE-754 accumulation (e.g. 0.90+0.05 → 0.9500…01).
        if self.total_vram > MAX_VRAM_UTILIZATION + 1e-3:
            raise ValueError(
                f"Total VRAM utilization ({vram_pct:.1f}%) exceeds "
                f"ceiling ({MAX_VRAM_UTILIZATION * 100:.0f}%)."
            )

        if self.total_vram < 0.85:
            logger.warning(
                f"⚠️ VRAM under-utilized: {vram_pct:.1f}%. "
                f"Consider increasing gpu_memory_utilization to maximize KV cache."
            )

        logger.info("✅ Memory Law constraints verified.")

    async def build(self):
        if not self.allow_no_embedding:
            has_embedding = any(
                req.role == "embedding"
                or "embedding" in req.recipe.lower()
                or "bge" in req.recipe.lower()
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
            shutil.copy2(OPENCLAW_CONFIG_PATH, self.stack_dir / OPENCLAW_CONFIG_PATH.name)
            logger.info(
                f"📄 Copied openclaw config to {self.stack_dir / OPENCLAW_CONFIG_PATH.name}"
            )

        bench_dir = self.stack_dir / "benchmarks"
        if bench_dir.exists():
            shutil.rmtree(bench_dir)

        base_compose, base_litellm = self.registry.load_base_configs()

        self.docker_builder = DockerComposeFileBuilder(self.stack_dir, base_compose)
        ApiGatewayServiceConfigurator.configure(self.docker_builder, "2G")

        self.gateway_builder = LiteLLMBuilder(self.stack_dir, base_litellm)
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

    async def _process_model_request(self, idx: int, req: ModelRequest):
        recipe_name = req.recipe
        role = req.role

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

            if is_embedding:
                target_role = (
                    "embedding"
                    if "embedding" not in self.gateway_builder.added_roles
                    else slugify(recipe_name)
                )
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
            "overrides": req.overrides,
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
