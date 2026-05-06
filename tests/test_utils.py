from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sparkstack.core.utils import (
    CommandError,
    CommandResult,
    DockerProbe,
    HealthStatus,
    HttpProbe,
    LogProbe,
    ServiceHealthManager,
)


def test_command_result():
    result = CommandResult(returncode=0, stdout="success", stderr="", cmd=["echo", "success"])
    assert result.returncode == 0
    assert result.stdout == "success"
    assert result.cmd == ["echo", "success"]


def test_command_error():
    err = CommandError(returncode=1, stdout="", stderr="failed", cmd=["ls", "/nonexistent"])
    assert err.returncode == 1
    assert err.stderr == "failed"
    assert "exit code 1" in str(err)


@pytest.mark.asyncio
@patch("core.utils.async_run_command")
async def test_docker_probe_healthy(mock_run):
    # Mock 'docker inspect' returning running and healthy
    mock_run.return_value = CommandResult(returncode=0, stdout="running healthy", stderr="", cmd=[])
    probe = DockerProbe("test-container")
    result = await probe.probe()
    assert result == HealthStatus.HEALTHY
    mock_run.assert_called_once()


@pytest.mark.asyncio
@patch("core.utils.async_run_command")
async def test_docker_probe_crashed(mock_run):
    mock_run.return_value = CommandResult(returncode=0, stdout="exited none", stderr="", cmd=[])
    probe = DockerProbe("test-container")
    result = await probe.probe()
    assert result == HealthStatus.CRASHED


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
async def test_http_probe_healthy(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_get.return_value = mock_response

    probe = HttpProbe("http://localhost:8080/health")
    result = await probe.probe()
    assert result == HealthStatus.HEALTHY
    mock_get.assert_called_once_with("http://localhost:8080/health", timeout=2.0)


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get", new_callable=AsyncMock)
async def test_http_probe_starting(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_get.return_value = mock_response

    probe = HttpProbe("http://localhost:8080/health")
    result = await probe.probe()
    assert result == HealthStatus.STARTING


@pytest.mark.asyncio
@patch("core.utils.async_run_command")
async def test_log_probe_crash(mock_run):
    mock_run.return_value = CommandResult(
        returncode=0, stdout="Traceback (most recent call last):", stderr="", cmd=[]
    )
    probe = LogProbe("test-container")
    result = await probe.probe()
    assert result == HealthStatus.CRASHED


@pytest.mark.asyncio
@patch("core.utils.async_run_command")
async def test_log_probe_unknown(mock_run):
    mock_run.return_value = CommandResult(
        returncode=0, stdout="Server started successfully", stderr="", cmd=[]
    )
    probe = LogProbe("test-container")
    result = await probe.probe()
    assert result == HealthStatus.UNKNOWN


@pytest.mark.asyncio
async def test_service_health_manager_healthy():
    # Mock probes to immediately return HEALTHY
    mock_docker_probe = MagicMock(spec=DockerProbe)
    mock_docker_probe.probe = AsyncMock(return_value=HealthStatus.HEALTHY)

    manager = ServiceHealthManager("test-container", probes=[mock_docker_probe])
    is_ready = await manager.wait_for_ready(timeout=2, stream_logs=False)

    assert is_ready is True
    mock_docker_probe.probe.assert_called()


@pytest.mark.asyncio
async def test_service_health_manager_crashed():
    # Mock probes to immediately return CRASHED
    mock_docker_probe = MagicMock(spec=DockerProbe)
    mock_docker_probe.probe = AsyncMock(return_value=HealthStatus.CRASHED)

    manager = ServiceHealthManager("test-container", probes=[mock_docker_probe])
    is_ready = await manager.wait_for_ready(timeout=2, stream_logs=False)

    assert is_ready is False
    mock_docker_probe.probe.assert_called()
