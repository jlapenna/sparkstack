import os
import tempfile

import yaml

from sparkstack.core.env import (
    get_nested_value,
    resolve_yaml_path,
    set_env,
    set_nested_value,
)


def test_resolve_yaml_path_with_env(monkeypatch):
    """Verify that resolve_yaml_path honors SPARKSTACK_CONFIG_PATH env variable."""
    temp_dir = tempfile.gettempdir()
    custom_path = os.path.join(temp_dir, "custom_sparkstack.yaml")
    monkeypatch.setenv("SPARKSTACK_CONFIG_PATH", custom_path)

    resolved = resolve_yaml_path()
    assert str(resolved) == os.path.abspath(custom_path)


def test_nested_value_helpers():
    """Verify helper functions get_nested_value and set_nested_value work as expected."""
    d = {}
    set_nested_value(d, ("overlay", "headscale_server"), "10.0.0.1")
    assert d == {"overlay": {"headscale_server": "10.0.0.1"}}

    val = get_nested_value(d, ("overlay", "headscale_server"))
    assert val == "10.0.0.1"

    # Type coercion checks
    set_nested_value(d, ("overlay", "headscale_port"), "8080")
    assert d["overlay"]["headscale_port"] == 8080

    set_nested_value(d, ("hardware", "usable_spark_memory_gb"), "121.5")
    assert d["hardware"]["usable_spark_memory_gb"] == 121.5

    set_nested_value(d, ("enabled_services",), "SparkRun,OpenClaw")
    assert d["enabled_services"] == ["SparkRun", "OpenClaw"]


def test_set_env_routing(monkeypatch, tmp_path):
    """Verify set_env routes operational config to YAML and secrets/dev configs to .env."""
    # 1. Setup temporary directories and config targets
    temp_yaml = tmp_path / "sparkstack.yaml"
    temp_env = tmp_path / ".env"

    monkeypatch.setenv("SPARKSTACK_CONFIG_PATH", str(temp_yaml))
    monkeypatch.setattr("sparkstack.core.env.PROJECT_ROOT", tmp_path)

    # 2. Set an operational configuration
    set_env("SPARKSTACK_HEADSCALE_SERVER", "192.168.1.100")

    # 3. Verify it was written to YAML and NOT .env
    assert temp_yaml.exists()
    with open(temp_yaml) as f:
        yaml_data = yaml.safe_load(f)
    assert yaml_data["overlay"]["headscale_server"] == "192.168.1.100"
    assert not temp_env.exists()

    # 4. Set a development / secret configuration
    set_env("LITELLM_MASTER_KEY", "sk-test-secret-key-12345")

    # 5. Verify it went to .env and NOT YAML
    assert temp_env.exists()
    with open(temp_env) as f:
        env_content = f.read()
    assert "LITELLM_MASTER_KEY" in env_content
    assert "sk-test-secret-key-12345" in env_content

    with open(temp_yaml) as f:
        yaml_data = yaml.safe_load(f)
    assert "LITELLM_MASTER_KEY" not in yaml_data
