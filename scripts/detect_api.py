#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
from pathlib import Path

import asyncio
import json
import re

import yaml
from loguru import logger

from core.discovery import get_container_name_by_port
from core.utils import async_run_command


async def _run_in_container(cmd: list[str], container: str) -> tuple[str, str]:
    """Run a command inside a Docker container and return (stdout, stderr)."""
    full_cmd = ["docker", "exec", container] + cmd
    try:
        result = await async_run_command(full_cmd, check=False)
        return result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return "", str(e)


async def _run_local(cmd: list[str]) -> tuple[str, str]:
    """Run a command on the host and return (stdout, stderr)."""
    try:
        result = await async_run_command(cmd, check=False)
        return result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return "", str(e)


async def detect_api():
    logger.info("Probing NVIDIA Spark Stack...")

    # 1. Discover Main Container
    stack_dir = Path(__file__).parent.parent / "current"
    litellm_file = stack_dir / "litellm-config.yaml"
    main_container = None

    if litellm_file.exists():
        with open(litellm_file) as f:
            config = yaml.safe_load(f)
        for model in config.get("model_list", []):
            if model.get("model_name") in ["main"]:
                api_base = model.get("litellm_params", {}).get("api_base", "")
                match = re.search(r":(\d+)", api_base)
                if match:
                    port = int(match.group(1))
                    main_container = await get_container_name_by_port(port)
                    if main_container:
                        break

    if not main_container:
        logger.error("Could not identify active main container. Is the stack running?")
        return None

    logger.info(f"Found Main Container: {main_container}")

    report = {
        "container": main_container,
        "engine": "unknown",
        "features": {},
        "env": {},
        "hardware": "unknown",
    }

    # 2. Detect Engine Version
    v1_check, _ = await _run_in_container(["env"], main_container)
    if "VLLM_V1=1" in v1_check or 'VLLM_V1="1"' in v1_check:
        report["engine"] = "V1 (Experimental)"
    else:
        report["engine"] = "V0 (Stable)"

    # 3. Probe CLI flags
    help_out, _ = await _run_in_container(["vllm", "serve", "--help=all"], main_container)

    report["features"]["speculative_config_api"] = "--speculative-config" in help_out
    report["features"]["legacy_speculative_flags"] = "--speculative-model" in help_out
    report["features"]["draft_device_support"] = (
        "--speculative-draft-device" in help_out or "draft_load_config.device" in help_out
    )

    # 4. Check Environment Constraints
    report["env"]["hub_offline"] = (
        "HF_HUB_OFFLINE=1" in v1_check or 'HF_HUB_OFFLINE="1"' in v1_check
    )

    inspect_out, _ = await _run_local(["docker", "inspect", main_container])
    try:
        inspect_data = json.loads(inspect_out)
        mounts = inspect_data[0].get("Mounts", [])
        for m in mounts:
            if m.get("Destination") == "/cache/huggingface":
                report["env"]["hf_cache_host_path"] = m.get("Source")
    except (json.JSONDecodeError, IndexError, KeyError):
        pass

    # 5. Detect Hardware
    gpu_out, _ = await _run_local(["nvidia-smi", "--query-gpu=gpu_name", "--format=csv,noheader"])
    report["hardware"] = gpu_out.split("\n")[0] if gpu_out else "unknown"

    # Print Summary
    print("\n--- PRE-FLIGHT DISCOVERY REPORT ---")
    print(f"GPU Hardware   : {report['hardware']}")
    print(f"vLLM Engine    : {report['engine']}")
    print(
        f"Speculative API: {'Unified (JSON)' if report['features']['speculative_config_api'] else 'Legacy (Flags)'}"
    )
    print(f"Offline Mode   : {'ENABLED' if report['env']['hub_offline'] else 'disabled'}")
    if report["env"].get("hf_cache_host_path"):
        print(f"HF Cache Path  : {report['env']['hf_cache_host_path']}")

    print("\n--- API COMPATIBILITY ---")
    for feat, supported in report["features"].items():
        status = "✅ Supported" if supported else "❌ Unsupported"
        print(f"{feat:<25}: {status}")

    if report["hardware"] == "NVIDIA Blackwell GB10" and "NVFP4" not in help_out:
        logger.warning("Hardware is Blackwell but NVFP4 support not detected in help menu.")

    return report


def main():
    asyncio.run(detect_api())


if __name__ == "__main__":
    main()
