import json

import pytest
import yaml

from sparkstack.core.builders.docker import DockerComposeFileBuilder
from sparkstack.core.builders.litellm import LiteLLMBuilder
from sparkstack.core.builders.monitoring import MonitoringBuilder


@pytest.fixture
def temp_stack_dir(tmp_path):
    return tmp_path


def test_compose_builder(temp_stack_dir):
    base_config = {"services": {"gateway": {"image": "nginx"}}}
    builder = DockerComposeFileBuilder(temp_stack_dir, base_config)

    builder.add_service("backend", {"image": "my-backend", "ports": ["8080:80"]})
    builder.write()

    compose_file = temp_stack_dir / "docker-compose.yaml"
    assert compose_file.exists()

    with compose_file.open("r") as f:
        config = yaml.safe_load(f)

    assert "backend" in config["services"]
    assert config["services"]["backend"] == {"image": "my-backend", "ports": ["8080:80"]}


def test_litellm_builder(temp_stack_dir):
    base_config = {"model_list": [], "litellm_settings": {}}
    builder = LiteLLMBuilder(temp_stack_dir, base_config)

    builder.add_model(
        role_id="main",
        backend_model="hosted_vllm/qwen",
        backend_url="http://localhost:8000/v1",
        context_window=8192,
        human_name="Qwen 1.5",
        model_info={"input": ["text"]},
    )

    builder.write()
    litellm_file = temp_stack_dir / "litellm-config.yaml"
    assert litellm_file.exists()

    with litellm_file.open("r") as f:
        config = yaml.safe_load(f)

    assert len(config["model_list"]) == 1
    model_cfg = config["model_list"][0]
    assert model_cfg["model_name"] == "main"
    assert model_cfg["litellm_params"]["model"] == "openai/hosted_vllm/qwen"
    assert model_cfg["litellm_params"]["api_base"] == "http://localhost:8000/v1"
    assert model_cfg["model_info"]["context_window"] == 8192
    # role_map should NOT be injected — global litellm_setting handles it
    assert "role_map" not in model_cfg["litellm_params"]
    # input should NOT be in model_info — it's an OpenClaw-only field
    assert "input" not in model_cfg["model_info"]

    # Verify OpenClaw models.json: max_tokens defaults to context_window
    models_file = temp_stack_dir / "models.json"
    assert models_file.exists()
    with models_file.open("r") as f:
        models_config = json.load(f)
    spark_model = models_config["spark"]["models"][0]
    assert spark_model["maxTokens"] == 8192  # defaults to context_window
    assert spark_model["contextWindow"] == 8192


def test_litellm_builder_openai_responses_api(temp_stack_dir):
    base_config = {"model_list": [], "litellm_settings": {}}
    builder = LiteLLMBuilder(temp_stack_dir, base_config)

    builder.add_model(
        role_id="main",
        backend_model="hosted_vllm/qwen",
        backend_url="http://localhost:8000/v1",
        context_window=8192,
        human_name="Qwen 1.5",
        model_info={
            "input": ["text"],
            "api": "openai-responses",
            "supports_prompt_cache_key": True,
            "supports_store": True,
        },
    )

    builder.write()
    models_file = temp_stack_dir / "models.json"
    assert models_file.exists()

    with models_file.open("r") as f:
        config = json.load(f)

    spark_models = config["spark"]["models"]
    assert len(spark_models) == 1
    model_cfg = spark_models[0]

    assert model_cfg["api"] == "openai-responses"
    assert model_cfg["compat"]["supportsPromptCacheKey"] is True
    assert model_cfg["compat"]["supportsStore"] is True


def test_prometheus_builder(temp_stack_dir):
    builder = MonitoringBuilder(temp_stack_dir)
    builder.add_target("localhost:8001", "main")
    builder.add_target("localhost:8002", "embedding")

    builder.write()
    prom_file = temp_stack_dir / "targets.json"
    assert prom_file.exists()

    with prom_file.open("r") as f:
        config = json.load(f)

    # Scrape_configs has no static_cfgs, so target 0 is main
    assert len(config) == 2
    assert config[0]["targets"] == ["localhost:8001"]
    assert config[0]["labels"]["model"] == "main"
    assert config[1]["targets"] == ["localhost:8002"]
    assert config[1]["labels"]["model"] == "embedding"
