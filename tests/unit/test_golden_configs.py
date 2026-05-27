import json
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sparkstack.core.registry import SparkrunRegistryModel
from sparkstack.manager.services import (
    HeadscaleService,
    InferenceStackService,
    MonitoringService,
    ServiceState,
)
from sparkstack.manager.update_services import Settings


@pytest.fixture
def mock_execution_logger():
    """Captures all shell/ssh/compose commands."""
    log = []

    async def mock_run_command(cmd, *args, **kwargs):
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = cmd
        env_str = ""
        if kwargs.get("env"):
            env_str = f"[ENV: DOCKER_HOST={kwargs['env'].get('DOCKER_HOST', '')}] "
        log.append(f"[CMD] {env_str}{cmd_str}")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        # specific command responses
        if "headscale preauthkeys create" in cmd_str:
            mock_result.stdout = "mock_auth_key\n"
        elif "tailscale ip -4" in cmd_str:
            mock_result.stdout = "100.64.0.10\n"
        elif "tailscale status --json" in cmd_str:
            mock_result.stdout = '{"BackendState": "Running"}\n'
        elif "docker inspect" in cmd_str:
            mock_result.stdout = '[{"State": {"Health": {"Status": "healthy"}}}]\n'

        return mock_result

    async def mock_run_ssh(target, cmd, *args, **kwargs):
        log.append(f"[SSH:{target}] {cmd}")

        if "headscale preauthkeys create" in cmd:
            return "mock_auth_key\n"
        if "tailscale ip -4" in cmd:
            return "100.64.0.10\n"
        if "tailscale status --json" in cmd:
            return '{"BackendState": "Running"}\n'
        if "docker inspect" in cmd:
            return '[{"State": {"Health": {"Status": "healthy"}}}]\n'

        return ""

    async def mock_run_compose(directory, *args, **kwargs):
        cmd_str = " ".join(args)
        env_str = ""
        if kwargs.get("env"):
            env_str = f"[ENV: DOCKER_HOST={kwargs['env'].get('DOCKER_HOST', '')}] "
        log.append(f"[COMPOSE:{directory.name}] {env_str}{cmd_str}")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        return mock_result

    return log, mock_run_command, mock_run_ssh, mock_run_compose


@pytest.mark.asyncio
async def test_golden_stack_generation(tmp_path, request, monkeypatch, mock_execution_logger):
    """
    Generate golden configuration files and assert they haven't changed unexpectedly.
    """
    # 1. Mock hardware constraints so the generated configs are deterministic
    monkeypatch.setattr("sparkstack.core.builders.stack.USABLE_SPARK_MEMORY_GB", 150.0)
    monkeypatch.setattr("sparkstack.core.builders.stack.SYSTEM_RESERVED_MEMORY_GB", 12.0)
    monkeypatch.setattr("sparkstack.core.builders.stack.SPARKSTACK_MONITORING_OVERHEAD_GB", 5.0)
    monkeypatch.setattr("sparkstack.core.builders.stack.MAX_DOCKER_MEMORY_GB", 138.0)

    # Force overlay to True so headscale executes
    monkeypatch.setattr("sparkstack.core.env.SPARKSTACK_HEADSCALE_SERVER", "http://headscale:8080")
    monkeypatch.setattr("sparkstack.core.env.SPARKSTACK_HEADSCALE_AUTH_KEY", "")

    # 2. Mock the registry and sparkrun handler
    mock_recipe = SparkrunRegistryModel(
        identity="test-model",
        name="test-model",
        image="vllm/vllm-openai:latest",
        memory_usage_gb=20.0,
        vram_usage=0.16,
        recipe={},
        recipe_path="test-recipe-path",
        model_name="meta-llama/Llama-3-70b-Instruct",
        environment={},
    )

    # 3. Setup a fake 'current' stack directory with our topology
    current_dir = tmp_path / "current"
    current_dir.mkdir()

    stack_def = {
        "version": "1",
        "name": "golden-stack",
        "backends": [
            {
                "name": "model-a",
                "recipe": "vllm-70b-awq",
                "target": "user@remote-worker",
                "is_remote": True,
                "port": 8001,
            }
        ],
    }
    with open(current_dir / "stack.yaml", "w") as f:
        yaml.dump(stack_def, f)

    # Need dummy docker-compose files for pulling
    (tmp_path / "services" / "headscale").mkdir(parents=True)
    (tmp_path / "services" / "headscale" / "docker-compose.yml").write_text("services: {}")
    (tmp_path / "services" / "monitoring").mkdir(parents=True)
    (tmp_path / "services" / "monitoring" / "docker-compose.yml").write_text("services: {}")

    settings = Settings(project_root=tmp_path)

    execution_log, mock_run_cmd, mock_run_ssh, mock_run_compose = mock_execution_logger

    # 4. Mock dependencies using monkeypatch
    monkeypatch.setattr(
        "sparkstack.core.registry.ModelRegistry.load_model", AsyncMock(return_value=mock_recipe)
    )
    monkeypatch.setattr(
        "sparkstack.core.builders.stack.StackBuilder._validate_configs", MagicMock()
    )
    monkeypatch.setattr("sparkstack.manager.launch.async_run_command", mock_run_cmd)
    monkeypatch.setattr("sparkstack.manager.launch.async_run_compose", mock_run_compose)
    monkeypatch.setattr("sparkstack.manager.services.async_run_compose", mock_run_compose)
    monkeypatch.setattr("sparkstack.manager.remote.run_ssh_command", mock_run_ssh)
    monkeypatch.setattr("sparkstack.manager.services.Service._probe_health", AsyncMock())
    monkeypatch.setattr(
        "sparkstack.manager.remote.get_headscale_auth_key", AsyncMock(return_value="mock_auth_key")
    )
    monkeypatch.setattr(
        "sparkstack.manager.remote.resolve_head_tailnet_ip", AsyncMock(return_value="100.64.0.1")
    )
    monkeypatch.setattr("sparkstack.manager.remote.deploy_head_sidecar", AsyncMock())

    # 4. Run the orchestrator services
    headscale_svc = HeadscaleService("Headscale", ServiceState("Headscale"), settings)
    await headscale_svc.update()

    monitoring_svc = MonitoringService("Monitoring", ServiceState("Monitoring"), settings)
    await monitoring_svc.update()

    inference_svc = InferenceStackService(
        "InferenceStack", ServiceState("InferenceStack"), settings
    )
    await inference_svc.update()

    # Write execution log to file
    log_content = "\n".join(execution_log) + "\n"
    log_content = log_content.replace(str(tmp_path), "<TMP_PATH>")
    (current_dir / "execution_log.txt").write_text(log_content)

    # 5. Assert generated files against the golden directory
    golden_dir = Path(__file__).parent / "golden_stacks" / "default"
    update_goldens = request.config.getoption("--update-goldens", default=False)

    if update_goldens:
        golden_dir.mkdir(parents=True, exist_ok=True)

    expected_files = [
        "docker-compose.yaml",
        "prometheus.yml",
        "litellm-config.yaml",
        "models.json",
        "stack.yaml",
        "execution_log.txt",
    ]
    for f in expected_files:
        gen_path = current_dir / f
        golden_path = golden_dir / f

        if not gen_path.exists():
            continue

        gen_content = gen_path.read_text()

        if update_goldens:
            golden_path.write_text(gen_content)
        else:
            assert golden_path.exists(), (
                f"Missing golden file {f}. Run pytest with --update-goldens"
            )
            golden_content = golden_path.read_text()
            assert gen_content == golden_content, f"Mismatch in generated config: {f}"
