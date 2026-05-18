from unittest.mock import MagicMock, patch

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
