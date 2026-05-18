from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sparkstack.manager.update_services import Orchestrator, Settings


@pytest.mark.asyncio
async def test_orchestrator_initialization():
    """
    Test that the Orchestrator can be initialized correctly.
    This helps ensure that all service classes are imported and registered
    correctly, preventing regressions where a service is renamed but its
    reference in update_services.py is not updated.
    """
    mock_settings = Settings(pull_latest=False, project_root=Path("/tmp"))
    mock_ipc = MagicMock()

    # Instantiating the Orchestrator will fail if imports are broken
    # or if the Service classes are not available.
    orchestrator = Orchestrator(settings=mock_settings, ipc=mock_ipc)

    # Verify that the expected services are registered
    expected_services = {
        "SparkRun",
        "Cloudflare",
        "InferenceStack",
        "RegistrySync",
        "Monitoring",
        "OpenClaw",
        "Headscale",
    }

    registered_services = {s.name for s in orchestrator.services}

    assert registered_services == expected_services
    assert set(orchestrator.states.keys()) == expected_services
