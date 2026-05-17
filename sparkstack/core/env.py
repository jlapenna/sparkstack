"""
System-wide constants and constraints.
"""

import os
from pathlib import Path

import dotenv

PROJECT_ROOT = Path(
    os.getenv("SPARK_STACK_ROOT") or str(Path(__file__).resolve().parent.parent.parent)
).absolute()
REGISTRY_DIR = Path(
    os.getenv("SPARK_STACK_REGISTRY") or str(PROJECT_ROOT / "sparkstack-registry")
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

# Memory reserved for the host OS, kernel, Docker daemon, SSH, VS Code Server,
# monitoring containers, and other non-workload processes.  This must be large
# enough to prevent OOM kernel panics during transient model-loading spikes.
SYSTEM_RESERVED_MEMORY_GB = float(os.getenv("SPARK_STACK_SYSTEM_RESERVED_MEMORY_GB", 12.0))

# Strict ceiling for the sum of all workload container memory limits.
# Derived from total usable minus the system reserve.
MAX_DOCKER_MEMORY_GB = USABLE_SPARK_MEMORY_GB - SYSTEM_RESERVED_MEMORY_GB

# NVIDIA Blackwell Resource Constraints (Memory Law)
MAX_VRAM_UTILIZATION = float(os.getenv("MAX_VRAM_UTILIZATION", 0.95))
DEFAULT_KV_CACHE_CEILING = int(os.getenv("DEFAULT_KV_CACHE_CEILING", 128000))

# --- Detached Service Locations ---

# The 'sparkrun' command to execute. Defaults to searching in PATH.
_sparkrun_bin = os.getenv("SPARKRUN_BIN", "uv run sparkrun")
SPARKRUN_CMD = _sparkrun_bin.split()

# The directory containing the sparkrun source (for updates).
SPARKRUN_DIR = Path(os.getenv("SPARKRUN_DIR") or str(PROJECT_ROOT.parent / "sparkrun")).absolute()

# The directory containing the openclaw source (for updates).
OPENCLAW_DIR = Path(os.getenv("OPENCLAW_DIR") or str(PROJECT_ROOT.parent / "openclaw")).absolute()

# The directory containing custom skills to install into the OpenClaw sandbox.
SPARK_STACK_OPENCLAW_SKILLS_DIR = Path(
    os.getenv("SPARK_STACK_OPENCLAW_SKILLS_DIR")
    or str(PROJECT_ROOT / "services" / "openclaw" / "skills")
).absolute()

# --- Monitoring Ownership ---
# When set, sparkstack skips deploying Prometheus/Grafana/Tempo and configures
# Alloy to push metrics and traces to the specified external host instead.
SPARK_MONITORING_HOST = os.getenv("SPARK_MONITORING_HOST", "")

# Derived endpoints (individually overridable for split deployments)
REMOTE_PROMETHEUS_URL = os.getenv(
    "REMOTE_PROMETHEUS_URL",
    f"http://{SPARK_MONITORING_HOST}:9090" if SPARK_MONITORING_HOST else "",
)
REMOTE_TEMPO_URL = os.getenv(
    "REMOTE_TEMPO_URL",
    f"{SPARK_MONITORING_HOST}:4317" if SPARK_MONITORING_HOST else "",
)
REMOTE_GRAFANA_URL = os.getenv(
    "REMOTE_GRAFANA_URL",
    f"http://{SPARK_MONITORING_HOST}:3001" if SPARK_MONITORING_HOST else "",
)


def is_monitoring_external() -> bool:
    """True when sparkstack should use external monitoring backends."""
    return bool(SPARK_MONITORING_HOST)


# --- vLLM Backend Configuration ---

BACKEND_START_PORT = int(os.getenv("BACKEND_START_PORT", 8001))

VLLM_ENV: dict[str, str] = {
    "OTEL_ATTRIBUTE_VALUE_LENGTH_LIMIT": "131072",
}

BLACKWELL_MANDATORY_ENV: dict[str, str] = VLLM_ENV | {
    "VLLM_ATTENTION_BACKEND": "FLASHINFER",
    "VLLM_FLASHINFER_MOE_BACKEND": "latency",
    "VLLM_BLACKWELL_LAYOUT": "1",
    "VLLM_BLACKWELL_UMA_OVERLAP": "1",
    "VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8": "1",
    "VLLM_USE_DEEP_GEMM": "0",
}
