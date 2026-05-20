import os
from pathlib import Path

from sparkstack.manager.update_services import Settings


def test_settings_default_no_enabled_services():
    """Verify that by default, when SPARKSTACK_ENABLED_SERVICES is not set, target_services is None."""
    # Ensure it's not set in env
    env_key = "SPARKSTACK_ENABLED_SERVICES"
    old_val = os.environ.pop(env_key, None)

    try:
        settings = Settings(
            pull_latest=False,
            project_root=Path("/tmp"),
            target_services=None,
            _env_file=None,  # type: ignore
        )
        assert settings.target_services is None
    finally:
        if old_val is not None:
            os.environ[env_key] = old_val


def test_settings_enabled_services_parsing():
    """Verify that settings correctly parses SPARKSTACK_ENABLED_SERVICES when target_services is None."""
    env_key = "SPARKSTACK_ENABLED_SERVICES"
    old_val = os.environ.pop(env_key, None)
    os.environ[env_key] = "OpenClaw,InferenceStack,RegistrySync"

    try:
        settings = Settings(
            pull_latest=False,
            project_root=Path("/tmp"),
            target_services=None,
            _env_file=None,  # type: ignore
        )
        assert settings.target_services == ("OpenClaw", "InferenceStack", "RegistrySync")
    finally:
        os.environ.pop(env_key, None)
        if old_val is not None:
            os.environ[env_key] = old_val


def test_settings_explicit_target_services_overrides_env():
    """Verify that explicitly passed target_services overrides SPARKSTACK_ENABLED_SERVICES."""
    env_key = "SPARKSTACK_ENABLED_SERVICES"
    old_val = os.environ.pop(env_key, None)
    os.environ[env_key] = "OpenClaw,InferenceStack"

    try:
        settings = Settings(
            pull_latest=False,
            project_root=Path("/tmp"),
            target_services=("Monitoring", "Cloudflare"),
            _env_file=None,  # type: ignore
        )
        assert settings.target_services == ("Monitoring", "Cloudflare")
    finally:
        os.environ.pop(env_key, None)
        if old_val is not None:
            os.environ[env_key] = old_val
