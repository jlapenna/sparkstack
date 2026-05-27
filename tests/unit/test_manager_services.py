from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sparkstack.core.schemas import ServiceStatus
from sparkstack.manager.services import ServiceState, SparkrunService


@pytest.mark.asyncio
async def test_service_state_broadcast():
    mock_ipc = MagicMock()
    state = ServiceState("test-service", ipc=mock_ipc)

    state.set_task("Starting", 10.0)
    assert state.status == ServiceStatus.RUNNING
    assert state.progress == 10.0
    assert mock_ipc.update_state.called


@pytest.mark.asyncio
async def test_service_state_complete():
    mock_ipc = MagicMock()
    state = ServiceState("test-service", ipc=mock_ipc)

    state.complete()
    assert state.status == ServiceStatus.COMPLETE
    assert state.progress == 100.0
    assert state.done_event.is_set()


@pytest.mark.asyncio
async def test_sparkrun_service_update():
    mock_state = MagicMock()
    mock_settings = MagicMock(pull_latest=False, project_root="/tmp")

    service = SparkrunService("SparkRun", mock_state, mock_settings)

    with patch("sparkstack.manager.services.SparkrunService.updater_class") as mock_updater_cls:
        mock_updater = mock_updater_cls.return_value

        async def mock_events():
            yield "Task 1", 50.0
            yield "Task 2", 100.0

        mock_updater.run_events.return_value = mock_events()

        await service.update()

        assert mock_state.set_task.call_count == 2
        assert mock_state.complete.called


@pytest.mark.asyncio
async def test_headscale_service_worker_isolation():
    from pathlib import Path

    from sparkstack.manager.services import HeadscaleService

    mock_state = MagicMock()
    mock_settings = MagicMock(pull_latest=False, project_root=Path("/tmp"))

    service = HeadscaleService("Headscale", mock_state, mock_settings)
    service.deploy = MagicMock()
    service._pull_images = AsyncMock(return_value=2)
    service._deploy_compose = AsyncMock(return_value=3)
    service._probe_health = AsyncMock()
    service.progress = MagicMock()

    with (
        patch("sparkstack.core.env.is_overlay_configured", return_value=True),
        patch("sparkstack.manager.services._render_headscale_config"),
        patch("sparkstack.core.env.SPARKSTACK_HEADSCALE_AUTH_KEY", "key"),
        patch("sparkstack.core.env.SPARKSTACK_HEAD_TAILNET_IP", "100.64.0.1"),
        patch("sparkstack.core.env.SPARK_NODE_TARGET", "ssh://user@worker1"),
        patch("sparkstack.core.env.WORKER_TAILNET_IP", ""),
        patch("sparkstack.core.env.get_headscale_url", return_value="http://127.0.0.1:8080"),
        patch("sparkstack.manager.remote.deploy_head_sidecar", new_callable=AsyncMock),
        patch(
            "sparkstack.manager.remote.poll_sidecar_health",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "sparkstack.manager.remote.resolve_worker_tailnet_ip",
            new_callable=AsyncMock,
            return_value="100.64.0.2",
        ),
        patch(
            "sparkstack.manager.remote.deploy_worker_sidecar", new_callable=AsyncMock
        ) as mock_deploy_worker,
    ):
        # Simulate worker deployment failing
        mock_deploy_worker.side_effect = Exception("Simulated network blip")

        # The update should still complete without raising the exception
        await service.update()

        assert mock_deploy_worker.called
        # It shouldn't have failed the whole state due to the error isolation
        assert not mock_state.fail.called
