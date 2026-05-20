import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from sparkstack.manager.launch import _deploy_remote_infrastructure, _extract_hostname, launch_stack


def test_extract_hostname():
    assert _extract_hostname("ssh://user@host") == "host"
    assert _extract_hostname("user@host:port") == "host"
    assert _extract_hostname("host") == "host"
    assert _extract_hostname("ssh://host") == "host"
    assert _extract_hostname("ssh://user@spark-node:22") == "spark-node"


@pytest.mark.asyncio
async def test_deploy_remote_infrastructure_no_overlay():
    stack = {"backends": [{"name": "main", "is_remote": True, "target": "user@spark"}]}
    stack_dir = Path("/tmp/dummy")

    with (
        patch("sparkstack.core.env.is_overlay_configured", return_value=False),
        patch("sparkstack.manager.remote.deploy_head_sidecar", new_callable=AsyncMock) as mock_head,
    ):
        await _deploy_remote_infrastructure(stack, stack_dir)
        mock_head.assert_not_called()


@pytest.mark.asyncio
async def test_deploy_remote_infrastructure_success(tmp_path):
    stack = {
        "cluster_name": "test-cluster",
        "backends": [
            {"name": "main", "is_remote": True, "target": "user@spark"},
            {"name": "embedding", "is_remote": True, "target": "user@oldbook"},
            {"name": "local", "is_remote": False, "target": "localhost"},
        ],
    }

    with (
        patch("sparkstack.core.env.is_overlay_configured", return_value=True),
        patch("sparkstack.core.env.SPARKSTACK_HEADSCALE_AUTH_KEY", "test-auth-key"),
        patch("sparkstack.core.env.get_headscale_url", return_value="http://127.0.0.1:8080"),
        patch(
            "sparkstack.manager.remote.deploy_head_sidecar", new_callable=AsyncMock
        ) as mock_deploy_head,
        patch(
            "sparkstack.manager.remote.deploy_worker_sidecar", new_callable=AsyncMock
        ) as mock_deploy_worker,
        patch(
            "sparkstack.manager.remote.resolve_worker_tailnet_ip", new_callable=AsyncMock
        ) as mock_resolve_ip,
        patch(
            "sparkstack.core.builders.stack.StackBuilder.rebuild_from_stack", new_callable=AsyncMock
        ) as mock_rebuild,
    ):
        mock_resolve_ip.side_effect = lambda target, hostname: (
            f"100.64.0.{'2' if hostname == 'spark' else '3'}"
        )

        await _deploy_remote_infrastructure(stack, tmp_path)

        mock_deploy_head.assert_called_once()
        assert mock_deploy_worker.call_count == 2
        mock_deploy_worker.assert_any_call(
            "user@spark", "spark", "test-auth-key", "http://127.0.0.1:8080"
        )
        mock_deploy_worker.assert_any_call(
            "user@oldbook", "oldbook", "test-auth-key", "http://127.0.0.1:8080"
        )

        assert mock_resolve_ip.call_count == 2
        mock_resolve_ip.assert_any_call("user@spark", "spark")
        mock_resolve_ip.assert_any_call("user@oldbook", "oldbook")

        mock_rebuild.assert_called_once_with(tmp_path)

        # Check state file written
        state_file = tmp_path / ".state.json"
        assert state_file.exists()

        state = json.loads(state_file.read_text())
        assert state["cluster_name"] == "test-cluster"
        assert state["sidecars"]["spark"]["tailnet_ip"] == "100.64.0.2"
        assert state["sidecars"]["oldbook"]["tailnet_ip"] == "100.64.0.3"


@pytest.mark.asyncio
async def test_launch_stack_local_and_remote(tmp_path):
    stack = {
        "backends": [
            {
                "name": "main",
                "recipe": "sparkrun/qwen3.6-35b-a3b.yaml",
                "target": "user@spark",
                "is_remote": True,
                "port": 8001,
                "tensor_parallel": 2,
                "memory_limit": "96G",
                "env": {"SOME_VAR": "val"},
                "labels": ["sparkrun.monitoring=true"],
                "overrides": {"gpu_memory_utilization": 0.85, "max_model_len": 4096},
            },
            {
                "name": "embedding",
                "recipe": "@jina-embedding",
                "target": "localhost",
                "is_remote": False,
                "port": 8002,
            },
        ]
    }

    stack_yaml = tmp_path / "stack.yaml"
    with open(stack_yaml, "w") as f:
        yaml.safe_dump(stack, f)

    mock_run = AsyncMock()
    mock_run.return_value.stdout = ""
    mock_run.return_value.returncode = 0

    mock_compose = AsyncMock()

    with (
        patch(
            "sparkstack.manager.launch._deploy_remote_infrastructure", new_callable=AsyncMock
        ) as mock_deploy_infra,
        patch("sparkstack.manager.launch.async_run_command", mock_run),
        patch("sparkstack.manager.launch.async_run_compose", mock_compose),
        patch.dict(os.environ, {"SPARKSTACK_HEAD_TAILNET_IP": "100.64.0.1"}),
    ):
        await launch_stack(tmp_path)

        mock_deploy_infra.assert_called_once()

        # Check command calls for sparkrun
        # The run_command call count should be:
        # 1. Stop all sparkrun containers (since state exists or read_sidecar_state has cluster)
        # 2. Removing stale local backend containers (docker ps -aq)
        # 3. sparkrun run main (remote)
        # 4. sparkrun run embedding (local)

        # Filter mock calls by sparkrun
        sparkrun_calls = [c[0][0] for c in mock_run.call_args_list if "sparkrun" in str(c[0][0])]

        # Remote sparkrun run command check
        remote_call = next(c for c in sparkrun_calls if "--served-model-name" in c and "main" in c)
        assert "--hosts" in remote_call
        assert "user@spark" in remote_call
        assert "--port" in remote_call
        assert "8001" in remote_call
        assert "--tp" in remote_call
        assert "2" in remote_call
        assert "--memory-limit" in remote_call
        assert "96G" in remote_call
        assert "--gpu-mem" in remote_call
        assert "0.85" in remote_call
        assert "--max-model-len" in remote_call
        assert "4096" in remote_call
        assert "-o" in remote_call
        assert "network=container:sparkstack-sidecar-spark" in remote_call
        assert "env.OTEL_EXPORTER_OTLP_ENDPOINT=http://100.64.0.1:4318" in remote_call
        assert "env.SOME_VAR=val" in remote_call
        assert "--label" in remote_call
        assert "sparkrun.monitoring=true" in remote_call

        # Local sparkrun run command check
        local_call = next(
            c for c in sparkrun_calls if "--served-model-name" in c and "embedding" in c
        )
        assert "--hosts" in local_call
        assert "localhost" in local_call
        assert "--port" in local_call
        assert "8002" in local_call
        assert "-o" in local_call
        assert "network=sparkstack-net" in local_call

        # Compose up verification
        mock_compose.assert_called_once()
        args, kwargs = mock_compose.call_args
        assert args[0] == tmp_path
        assert "up" in args
        assert "-d" in args
