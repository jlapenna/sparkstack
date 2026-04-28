"""
core/constants.py - System-wide constants and constraints.
"""

import os
from pathlib import Path

import dotenv

PROJECT_ROOT = Path(
    os.getenv("SPARK_STACK_ROOT") or str(Path(__file__).resolve().parent.parent)
).absolute()
REGISTRY_DIR = Path(
    os.getenv("SPARK_STACK_REGISTRY") or str(PROJECT_ROOT / "spark-stack-registry")
).absolute()
BASE_DIR = PROJECT_ROOT / "services"
STACKS_DIR = REGISTRY_DIR / "stacks"


OPENCLAW_REPO = os.getenv("OPENCLAW_REPO", "https://github.com/openclaw/openclaw")

_openclaw_config_dir = os.getenv("OPENCLAW_CONFIG_DIR")
if not _openclaw_config_dir:
    raise ValueError(
        "OPENCLAW_CONFIG_DIR environment variable is not set. Please set it in your environment or .env file."
    )

OPENCLAW_CONFIG_DIR = Path(_openclaw_config_dir).absolute()
OPENCLAW_CONFIG_PATH = OPENCLAW_CONFIG_DIR / "openclaw.json"

OPENCLAW_ENV = dotenv.dotenv_values(OPENCLAW_CONFIG_DIR / ".env")
_openclaw_env_openclaw_config_dir = OPENCLAW_ENV.get("OPENCLAW_CONFIG_DIR")

if (
    _openclaw_env_openclaw_config_dir
    and Path(_openclaw_env_openclaw_config_dir).absolute() != OPENCLAW_CONFIG_DIR
):
    raise ValueError(
        "OPENCLAW_CONFIG_DIR environment variable does not match the one in the .env file."
    )

# DGX Spark (GB10) Hardware Specifications
# Usable pool after OS and driver overhead (as estimated by sparkrun)
USABLE_SPARK_MEMORY_GB = float(os.getenv("USABLE_SPARK_MEMORY_GB", 121.0))
# Strict ceiling to prevent swapping across the C2C link
MAX_DOCKER_MEMORY_GB = float(os.getenv("MAX_DOCKER_MEMORY_GB", 120.0))

# NVIDIA Blackwell Resource Constraints (Memory Law)
MAX_VRAM_UTILIZATION = float(os.getenv("MAX_VRAM_UTILIZATION", 0.95))
