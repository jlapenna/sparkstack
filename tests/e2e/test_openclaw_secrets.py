import glob
import json
import os

import pytest


def check_no_raw_secrets(config_path):
    if not os.path.exists(config_path):
        return

    with open(config_path) as f:
        data = json.load(f)

    violations = []

    # Keys that contain 'token', 'secret', 'key', 'password' but are actually just regular configurations
    whitelist_keys = [
        "reservetokens",
        "reservetokensfloor",
        "usertokenreadonly",
        "secrets",
        "1password",
    ]

    def check(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()

                # Recursively check first
                check(v, f"{path}.{k}")

                # Check for secrets
                if any(x in kl for x in ["token", "apikey", "api_key", "secret", "password"]):
                    if kl in whitelist_keys:
                        continue

                    if isinstance(v, str):
                        # A valid secret ref in string form must be an env var substitution
                        if not v.startswith("${") and v not in ["api-key"]:
                            violations.append(f"{path}.{k} is a raw string, should be a secret ref")
                    elif isinstance(v, dict) and "source" not in v:
                        # A secret ref object should have 'source'
                        violations.append(
                            f"{path}.{k} is a dict but missing 'source', not a valid secret ref"
                        )

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                check(item, f"{path}[{i}]")

    check(data, "root")

    assert not violations, (
        f"Found raw secrets or improperly formatted tokens in {config_path}:\n"
        + "\n".join(violations)
    )


def test_openclaw_runtime_secrets():
    """Verify that the active runtime openclaw.json contains no raw secrets."""
    config_path = os.path.expanduser("~/.openclaw/openclaw.json")
    if os.path.exists(config_path):
        check_no_raw_secrets(config_path)
    else:
        pytest.skip(f"Runtime config not found: {config_path}")


def test_openclaw_registry_secrets():
    """Verify that the registry openclaw.copy.json templates contain no raw secrets."""
    registry_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../../sparkstack-registry")
    )
    if not os.path.exists(registry_path):
        pytest.skip(f"Registry not found at {registry_path}")

    config_files = glob.glob(os.path.join(registry_path, "**", "openclaw.copy.json"), recursive=True)
    if not config_files:
        pytest.skip(f"No openclaw.copy.json files found in registry {registry_path}")

    for config_path in config_files:
        check_no_raw_secrets(config_path)
