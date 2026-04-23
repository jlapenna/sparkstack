#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import asyncio
import contextlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any


def get_container_name(target: str) -> str:
    """Resolve target name to actual container name (hybrid support)."""
    # 1. Direct match
    try:
        subprocess.run(["docker", "inspect", target], check=True, capture_output=True)
        return target
    except subprocess.CalledProcessError:
        pass

    # 2. Check for sparkrun alias in litellm-config
    try:
        stack_dir = Path(__file__).parent.parent.parent.parent / "current"
        litellm_file = stack_dir / "litellm-config.yaml"
        if litellm_file.exists():
            with open(litellm_file) as f:
                import yaml

                config = yaml.safe_load(f)
            for model in config.get("model_list", []):
                if model.get("model_name") == target:
                    api_base = model.get("litellm_params", {}).get("api_base", "")
                    match = re.search(r":(\d+)", api_base)
                    if match:
                        port = int(match.group(1))
                        # Find container publishing this port
                        result = subprocess.run(
                            ["docker", "ps", "--format", "{{.Names}}|{{.Ports}}"],
                            capture_output=True,
                            text=True,
                        )
                        for line in result.stdout.strip().split("\n"):
                            if f":{port}->" in line or f":{port}" in line:
                                return line.split("|")[0]
    except Exception:
        pass

    return target


async def check_health(model_name: str, human_name: str) -> bool:
    """Checks if the vLLM container is listening on port 8000."""
    loop = asyncio.get_running_loop()
    actual_container = get_container_name(model_name)

    check_cmd = [
        "docker",
        "exec",
        actual_container,
        "python3",
        "-c",
        (
            "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); "
            "s.settimeout(1); exit(0 if s.connect_ex(('127.0.0.1', 8000)) == 0 else 1)"
        ),
    ]
    try:
        await loop.run_in_executor(
            None, lambda: subprocess.run(check_cmd, check=True, capture_output=True)
        )
        return True
    except subprocess.CalledProcessError:
        print(
            f"⚠️  Error: {human_name} ({actual_container}) is not yet listening on port 8000. Skipping."
        )
        return False


def _sync_request(url: str, data: bytes, headers: dict[str, str]):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as response:
        return response.read()


async def run_latency_benchmark(
    model_name: str, human_name: str, endpoint: str, payload: dict[str, Any]
):
    print(f"--- {human_name} Async Latency ---")
    if not await check_health(model_name, human_name):
        return

    loop = asyncio.get_running_loop()
    api_key = os.environ.get("VLLM_SPARK_API_KEY", "")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    data = json.dumps(payload).encode("utf-8")
    url = f"http://localhost:4000{endpoint}"

    print(">> Warming up kernels...")
    with contextlib.suppress(Exception):
        await loop.run_in_executor(None, _sync_request, url, data, headers)

    concurrency = 5
    print(f">> Running {concurrency} concurrent requests...")
    start = time.perf_counter()
    tasks = [
        loop.run_in_executor(None, _sync_request, url, data, headers) for _ in range(concurrency)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    end = time.perf_counter()

    success = [r for r in results if not isinstance(r, Exception)]
    avg_ms = ((end - start) / concurrency) * 1000
    print(f">> Concurrency: {len(success)} ok, {len(results) - len(success)} failed")
    print(f">> Mean Latency: {avg_ms:.1f}ms")


async def run_audio_latency_benchmark(
    model_name: str, human_name: str, model_id: str, endpoint: str
):
    print(f"--- {human_name} Async Audio Latency ---")
    actual_container = get_container_name(model_name)
    if not await check_health(model_name, human_name):
        return

    wav_file = "/app/assets/stt/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8/test_wavs/en.wav"
    cmd = [
        "docker",
        "exec",
        actual_container,
        "curl",
        "-s",
        "-w",
        "\n%{http_code}",
        f"http://localhost:8000{endpoint}",
        "-H",
        "Content-Type: multipart/form-data",
        "-F",
        f"file=@{wav_file}",
        "-F",
        f"model={model_id}",
        "-F",
        "language=en",
    ]

    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    res = await loop.run_in_executor(
        None, lambda: subprocess.run(cmd, capture_output=True, text=True)
    )
    end = time.perf_counter()

    output = res.stdout.strip().split("\n")
    if not output:
        return
    http_code = output[-1]
    if http_code == "200":
        try:
            data = json.loads("\n".join(output[:-1]))
            print(f'>> Transcription: "{data.get("text", "")}"')
            print(f">> Latency: {(end - start) * 1000:.1f}ms")
        except Exception:
            print(f"❌ Parse error: {res.stdout}")
    else:
        print(f"❌ Error (HTTP {http_code})")


async def run_throughput_benchmark(
    model_name: str, human_name: str, model_id: str, config: dict[str, Any]
):
    print(f"--- {human_name} Throughput ---")
    actual_container = get_container_name(model_name)
    if not await check_health(model_name, human_name):
        return

    quick = os.environ.get("QUICK_MODE") == "1"
    in_len = (config.get("input_len", 1024) // 2) if quick else config.get("input_len", 1024)
    out_len = (config.get("output_len", 128) // 2) if quick else config.get("output_len", 128)
    conc = 2 if quick else config.get("concurrency", 2)
    prompts = 2 if quick else config.get("prompts", 2)

    cmd = [
        "docker",
        "exec",
        actual_container,
        "python3",
        "-m",
        "vllm.entrypoints.openai.api_server_benchmark",
        "--model",
        model_id,
        "--base-url",
        "http://localhost:8000",
        "--num-prompts",
        str(prompts),
        "--max-concurrency",
        str(conc),
        "--dataset-name",
        "random",
        "--random-input-len",
        str(in_len),
        "--random-output-len",
        str(out_len),
    ]
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, subprocess.run, cmd)
