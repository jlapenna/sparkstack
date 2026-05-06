import json
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".ruff_cache",
    ".pytest_cache",
    ".vscode",
    "__pycache__",
    ".worktrees",
    "sparkrun",
    "openclaw",
    "scratch",
}


def get_config_files(extensions):
    files = []
    for p in PROJECT_ROOT.rglob("*"):
        # Skip excluded directories
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        if p.is_file() and p.suffix.lower() in extensions:
            files.append(p)
    return files


@pytest.mark.parametrize("filepath", get_config_files({".json"}))
def test_json_files_are_valid(filepath: Path):
    try:
        with open(filepath, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        pytest.fail(f"Invalid JSON file {filepath.relative_to(PROJECT_ROOT)}: {e}")


@pytest.mark.parametrize("filepath", get_config_files({".yaml", ".yml"}))
def test_yaml_files_are_valid(filepath: Path):
    try:
        with open(filepath, encoding="utf-8") as f:
            # Safely load all YAML documents if there are multiple separated by ---
            list(yaml.safe_load_all(f))
    except Exception as e:
        pytest.fail(f"Invalid YAML file {filepath.relative_to(PROJECT_ROOT)}: {e}")
