from unittest.mock import AsyncMock, patch

import pytest

from sparkstack.core.utils.health import DockerProbe, HealthStatus, HttpProbe


@pytest.mark.asyncio
async def test_docker_probe_healthy():
    with patch(
        "sparkstack.core.utils.docker.DockerClient.get_status", new_callable=AsyncMock
    ) as mock_get_status:
        mock_get_status.return_value = ("running", "healthy")
        probe = DockerProbe("test-container")
        status = await probe.probe()
        assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_docker_probe_crashed():
    with patch(
        "sparkstack.core.utils.docker.DockerClient.get_status", new_callable=AsyncMock
    ) as mock_get_status:
        mock_get_status.return_value = ("exited", "none")
        probe = DockerProbe("test-container")
        status = await probe.probe()
        assert status == HealthStatus.CRASHED


@pytest.mark.asyncio
async def test_http_probe_healthy():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 200
        probe = HttpProbe("http://test.local")
        status = await probe.probe()
        assert status == HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_http_probe_starting():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.status_code = 503
        probe = HttpProbe("http://test.local")
        status = await probe.probe()
        assert status == HealthStatus.STARTING
