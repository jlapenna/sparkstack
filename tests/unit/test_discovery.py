from unittest.mock import AsyncMock, patch

import pytest
import yaml

from sparkstack.core.discovery import get_active_services, get_container_name_by_port


@pytest.mark.asyncio
async def test_get_container_name_by_port_remote():
    # is_remote=True should short-circuit and return None immediately
    res = await get_container_name_by_port(8001, is_remote=True)
    assert res is None


@pytest.mark.asyncio
async def test_get_container_name_by_port_normal_docker_ps():
    mock_run = AsyncMock()
    mock_run.return_value.stdout = (
        "litellm|0.0.0.0:4000->4000/tcp\nmain_solo|0.0.0.0:8001->8001/tcp\n"
    )
    mock_run.return_value.returncode = 0

    with patch("sparkstack.core.discovery.async_run_command", mock_run):
        res = await get_container_name_by_port(8001, is_remote=False)
        assert res == "main_solo"
        # Check that we only ran one docker ps command since we found a match in port publishing
        assert mock_run.call_count == 1


@pytest.mark.asyncio
async def test_get_container_name_by_port_host_network_ps_aux():
    mock_run = AsyncMock()
    # 1st call: docker ps (no match in port publishing)
    # 2nd call: docker ps listing running containers
    # 3rd call: docker exec ps aux for the running container (match!)
    mock_run.side_effect = [
        AsyncMock(stdout="some_container|8080/tcp\n", returncode=0),
        AsyncMock(stdout="sparkrun_container\n", returncode=0),
        AsyncMock(
            stdout="python3 -m vllm.entrypoints.openai.api_server --port 8001\n", returncode=0
        ),
    ]

    with patch("sparkstack.core.discovery.async_run_command", mock_run):
        res = await get_container_name_by_port(8001, is_remote=False)
        assert res == "sparkrun_container"
        assert mock_run.call_count == 3


@pytest.mark.asyncio
async def test_get_container_name_by_port_host_network_serve_sh():
    mock_run = AsyncMock()
    # 1st call: docker ps
    # 2nd call: docker ps names
    # 3rd call: docker exec ps aux (no match)
    # 4th call: docker exec cat /tmp/sparkrun_serve.sh (match!)
    mock_run.side_effect = [
        AsyncMock(stdout="some_container|8080/tcp\n", returncode=0),
        AsyncMock(stdout="sparkrun_container\n", returncode=0),
        AsyncMock(stdout="other process info\n", returncode=0),
        AsyncMock(
            stdout="#!/bin/bash\nexec python3 -m vllm.entrypoints.openai.api_server --port=8001\n",
            returncode=0,
        ),
    ]

    with patch("sparkstack.core.discovery.async_run_command", mock_run):
        res = await get_container_name_by_port(8001, is_remote=False)
        assert res == "sparkrun_container"
        assert mock_run.call_count == 4


@pytest.mark.asyncio
async def test_get_active_services(tmp_path):
    # Setup mock files
    compose_data = {
        "services": {
            "litellm": {
                "container_name": "sparkstack-litellm",
                "ports": ["4000:4000"],
            },
            "alloy": {
                "container_name": "alloy-collector",
                "ports": [{"published": 4318, "target": 4318}],
            },
        }
    }

    litellm_data = {
        "model_list": [
            {"model_name": "qwen", "litellm_params": {"api_base": "http://100.64.0.2:8001/v1"}},
            {
                "model_name": "local-model",
                "litellm_params": {"api_base": "http://localhost:8002/v1"},
            },
            {
                "model_name": "dns-model",
                "litellm_params": {"api_base": "http://named-container:8003/v1"},
            },
        ]
    }

    # Write yaml files
    with open(tmp_path / "docker-compose.yaml", "w") as f:
        yaml.safe_dump(compose_data, f)
    with open(tmp_path / "litellm-config.yaml", "w") as f:
        yaml.safe_dump(litellm_data, f)

    # Setup sidecar state mock
    sidecars_state = {
        "cluster_name": "test-cluster",
        "sidecars": {
            "spark": {
                "container_name": "sparkstack-sidecar-spark",
                "tailnet_ip": "100.64.0.2",
                "role": "worker",
            }
        },
    }

    with (
        patch("sparkstack.manager.remote.read_sidecar_state", return_value=sidecars_state),
        patch(
            "sparkstack.core.discovery.get_container_name_by_port", new_callable=AsyncMock
        ) as mock_get_container,
    ):
        mock_get_container.return_value = "local_solo"

        services = await get_active_services(tmp_path)

        # We expect:
        # 1. litellm (compose, port 4000)
        # 2. alloy (compose, port 4318)
        # 3. qwen (remote sparkrun backend, port 8001, Tailnet IP 100.64.0.2, container sparkstack-sidecar-spark)
        # 4. local-model (local sparkrun backend, port 8002, container local_solo)
        # 5. dns-model (docker DNS sparkrun backend, port 8003, container named-container)

        assert len(services) == 5

        # Check compose services
        compose_svcs = [s for s in services if s["type"] == "compose"]
        assert len(compose_svcs) == 2
        assert any(s["name"] == "sparkstack-litellm" and s["port"] == 4000 for s in compose_svcs)
        assert any(s["name"] == "alloy-collector" and s["port"] == 4318 for s in compose_svcs)

        # Check sparkrun services
        sparkrun_svcs = [s for s in services if s["type"] == "sparkrun"]
        assert len(sparkrun_svcs) == 3

        # Check remote service
        remote_svc = next(s for s in sparkrun_svcs if s["name"] == "backend:qwen")
        assert remote_svc["is_remote"] is True
        assert remote_svc["port"] == 8001
        assert remote_svc["container"] == "sparkstack-sidecar-spark"
        assert remote_svc["target_host"] == "spark"
        assert remote_svc["tailnet_ip"] == "100.64.0.2"

        # Check local service
        local_svc = next(s for s in sparkrun_svcs if s["name"] == "backend:local-model")
        assert local_svc["is_remote"] is False
        assert local_svc["port"] == 8002
        assert local_svc["container"] == "local_solo"

        # Check DNS service
        dns_svc = next(s for s in sparkrun_svcs if s["name"] == "backend:dns-model")
        assert dns_svc["is_remote"] is False
        assert dns_svc["port"] == 8003
        assert dns_svc["container"] == "named-container"
