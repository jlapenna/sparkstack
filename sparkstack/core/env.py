"""
System-wide constants and constraints.
"""

import logging
import os
from pathlib import Path

import dotenv

PROJECT_ROOT = Path(
    os.getenv("SPARK_STACK_ROOT") or str(Path(__file__).resolve().parent.parent.parent)
).absolute()
REGISTRY_DIR = Path(
    os.getenv("SPARK_STACK_REGISTRY") or str(PROJECT_ROOT / "sparkstack-registry")
).absolute()
SECRETS_DIR = PROJECT_ROOT / "secrets"

# Ensure .env is loaded (if exists) so these helpers return current values
dotenv.load_dotenv(PROJECT_ROOT / ".env")

BASE_DIR = PROJECT_ROOT / "services"
STACKS_DIR = REGISTRY_DIR / "stacks"


def set_env(key: str, value: str) -> None:
    """Set an environment variable and persist it in .env."""
    env_path = PROJECT_ROOT / ".env"
    os.environ[key] = value
    try:
        dotenv.set_key(str(env_path), key, value)
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to persist {key} to .env: {e}")


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


# --- Remote Node Targets ---
# These targets specify where the respective services should be deployed.
# They can be SSH targets (e.g., "ssh://user@host") or Docker context names.
# Leave empty to run the service locally on the Head node.

SPARK_NODE_TARGET = os.getenv("SPARK_NODE_TARGET", "")
OPENCLAW_NODE_TARGET = os.getenv("OPENCLAW_NODE_TARGET", "")
MONITORING_NODE_TARGET = os.getenv("MONITORING_NODE_TARGET", "")


# --- Headscale / Tailscale Overlay Network ---
# The Headscale control plane manages node identities, IP allocation, and
# pre-auth keys for the encrypted Tailscale overlay connecting cluster nodes.
# These are provisioned during `sparkstack setup` and persisted in .env.

# The routable address of the Headscale control plane (LAN IP:port).
# Auto-detected from the host's primary LAN IP; user-overridable.
SPARKSTACK_HEADSCALE_SERVER = os.getenv("SPARKSTACK_HEADSCALE_SERVER", "")

# The port Headscale listens on (also used for the docker-compose port mapping).
SPARKSTACK_HEADSCALE_PORT = int(os.getenv("SPARKSTACK_HEADSCALE_PORT", 8080))

# Reusable pre-auth key generated by `sparkstack setup`. Used by all
# Tailscale sidecars (head + workers) to authenticate with Headscale.
SPARKSTACK_HEADSCALE_AUTH_KEY = os.getenv("SPARKSTACK_HEADSCALE_AUTH_KEY", "")

# The Tailnet IP of the head node's sidecar. Resolved after the head sidecar
# connects and persisted in .env. Used by remote backends for OTEL endpoints
# and by LiteLLM config generation for reverse routing.
SPARKSTACK_HEAD_TAILNET_IP = os.getenv("SPARKSTACK_HEAD_TAILNET_IP", "")

# The Tailnet IP of the worker node. Set when the worker is a remote node on the overlay.
WORKER_TAILNET_IP = os.getenv("WORKER_TAILNET_IP", "")

# Pinned Tailscale client image version for all sidecars.
SPARKSTACK_TAILSCALE_VERSION = os.getenv("SPARKSTACK_TAILSCALE_VERSION", "v1.82.5")


def is_overlay_configured() -> bool:
    """True when the Headscale overlay network has been provisioned."""
    return bool(SPARKSTACK_HEADSCALE_SERVER)


def get_headscale_url() -> str:
    """Return the routable URL for the Headscale control plane."""
    if not SPARKSTACK_HEADSCALE_SERVER:
        return ""
    if SPARKSTACK_HEADSCALE_SERVER.startswith("http"):
        return SPARKSTACK_HEADSCALE_SERVER
    return f"http://{SPARKSTACK_HEADSCALE_SERVER}:{SPARKSTACK_HEADSCALE_PORT}"


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
