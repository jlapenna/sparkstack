"""
core/constants.py - System-wide constants and constraints.
"""

import os
from pathlib import Path

# Base paths with environment overrides for portability
PROJECT_ROOT = Path(os.getenv("SPARK_STACK_ROOT", Path(__file__).resolve().parent.parent)).absolute()
OPENCLAW_HOME = Path(os.getenv("OPENCLAW_CONFIG_DIR", os.getenv("OPENCLAW_HOME", Path.home() / ".openclaw"))).absolute()
OPENCLAW_CONFIG = OPENCLAW_HOME / "openclaw.json"
REGISTRY_DIR = Path(os.getenv("SPARK_STACK_REGISTRY", PROJECT_ROOT / "spark-stack-registry")).absolute()
BASE_DIR = PROJECT_ROOT / "registry"
STACKS_DIR = REGISTRY_DIR / "stacks"

# DGX Spark (GB10) Hardware Specifications
TOTAL_SHARED_RAM_GB = 128.0
# Usable pool after OS and driver overhead (as estimated by sparkrun)
USABLE_SPARK_MEMORY_GB = 121.0
# Strict ceiling to prevent swapping across the C2C link
MAX_DOCKER_MEMORY_GB = 120.0

# NVIDIA Blackwell Resource Constraints (Memory Law)
MAX_VRAM_UTILIZATION = 0.95

# Default Context Window
DEFAULT_CONTEXT_WINDOW = 32768
FRONTIER_CONTEXT_WINDOW = 1048576

# Ports
GATEWAY_PORT = 4000
BACKEND_START_PORT = 8001

# NVIDIA Blackwell mandatory environment variables for vLLM
BLACKWELL_MANDATORY_ENV: dict[str, str] = {
    "VLLM_ATTENTION_BACKEND": "FLASHINFER",
    "VLLM_FLASHINFER_MOE_BACKEND": "latency",
    "VLLM_BLACKWELL_LAYOUT": "1",
    "VLLM_BLACKWELL_UMA_OVERLAP": "1",
    "VLLM_USE_FLASHINFER_MOE_MXFP4_MXFP8": "1",
    "VLLM_USE_DEEP_GEMM": "0",
    # Tracing
    "VLLM_OTEL_TRACING_ENABLED": "1",
}

# Crash detection patterns shared by LogProbe and ServiceHealthManager
CRASH_PATTERNS: list[str] = [
    r"Traceback \(most recent call last\):",
    r"FATAL:",
    r"ERROR:.*failed",
    r"RuntimeError:",
    r"NotImplementedError:",
    r"AssertionError:",
]
