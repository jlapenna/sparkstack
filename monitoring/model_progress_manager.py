#!/usr/bin/env python3
import asyncio
import contextlib
import os
import re
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
from aiohttp import web
from loguru import logger

# Configuration
SOCKET_PATH = "/var/run/docker.sock"
STATSD_HOST = os.environ.get("SPARKRUN_STATSD_HOST", "vector")
STATSD_PORT = int(os.environ.get("SPARKRUN_STATSD_PORT", "8125"))
STATSD_ADDR = (STATSD_HOST, STATSD_PORT)
POLL_INTERVAL = 5.0
API_PORT = 8126

# Global state
active_monitors: dict[str, asyncio.Task] = {}
last_known_pct: dict[str, int] = {}
last_known_phase: dict[str, str] = {}
container_info_cache: dict[str, dict[str, Any]] = {}
# Phase tracking for MTP models (Main model + Drafter)
container_phases: dict[str, dict[str, int]] = {}

# Regex Compilations
FATAL_REGEX = re.compile(
    r"(?i)(?:AssertionError|RuntimeError|ValueError|error: argument|Exception:|Traceback|killed|Segmentation fault|Bus error|defunct|initialization failed|startup is less than desired)"
)
# Traditional Weights: "Loading safetensors... 50%"
PROGRESS_REGEX_PCT = re.compile(r"(?i)(?:load|fetch|download).*?(\d{1,3})%")
# FastSafetensors: "Loaded 22 / 133 chunks"
PROGRESS_REGEX_FRACT = re.compile(r"(?i)(?:load|fetch).*?(?P<cur>\d+)\s*/\s*(?P<tot>\d+)")
# CUDA Graphs
CUDA_GRAPH_REGEX = re.compile(r"(?i)Capturing CUDA graphs.*?(\d{1,3})%")

# Initialization Markers
ARCHITECTURE_REGEX = re.compile(r"(?i)Resolved architecture")
START_LOAD_REGEX = re.compile(r"(?i)Starting to load model")
WEIGHTS_LOADED_REGEX = re.compile(r"(?i)Loading weights took")
COMPILE_REGEX = re.compile(r"(?i)torch\.compile took")
PROFILING_REGEX = re.compile(r"(?i)Initial profiling/warmup")


class StatsdClient:
    def __init__(self) -> None:
        self.writer: asyncio.StreamWriter | None = None
        self.lock = asyncio.Lock()

    async def send(self, msg: str) -> None:
        async with self.lock:
            if self.writer is None or self.writer.is_closing():
                try:
                    _, self.writer = await asyncio.wait_for(
                        asyncio.open_connection(*STATSD_ADDR), timeout=2.0
                    )
                except Exception as e:
                    logger.debug(f"Failed to connect to StatsD: {e}")
                    self.writer = None
                    return
            try:
                self.writer.write(msg.encode("utf-8"))
                await self.writer.drain()
            except Exception as e:
                logger.debug(f"StatsD write exception: {e}")
                if self.writer:
                    with contextlib.suppress(Exception):
                        self.writer.close()
                    self.writer = None


statsd = StatsdClient()


async def push_to_statsd_tcp(metric: str, value: int, container_name: str, model_id: str) -> None:
    msg = f"{metric}:{value}|g|#name:{container_name},model_id:{model_id}\n"
    await statsd.send(msg)


async def push_worker() -> None:
    while True:
        for container_name, pct in list(last_known_pct.items()):
            info = container_info_cache.get(container_name, {})
            model_id = info.get("model_id", container_name)
            await push_to_statsd_tcp("model_load_progress", pct, container_name, model_id)
        await asyncio.sleep(10.0)


async def handle_api_request(request: web.Request) -> web.Response:
    res = {}
    for c, pct in last_known_pct.items():
        res[c] = {
            "pct": pct,
            "phase": last_known_phase.get(c, "Initializing...") if pct >= 0 else "Failed",
        }
    return web.json_response(res)


async def run_api_server() -> None:
    app = web.Application()
    app.router.add_get("/status", handle_api_request)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", API_PORT)
    logger.info(f"[API] Internal status API listening on port {API_PORT}")
    await site.start()


def get_docker_session() -> aiohttp.ClientSession:
    connector = aiohttp.UnixConnector(path=SOCKET_PATH)
    return aiohttp.ClientSession(connector=connector)


async def docker_api_get(endpoint: str) -> tuple[int, Any]:
    async with get_docker_session() as session, session.get(f"http://localhost{endpoint}") as resp:
        if resp.status == 200:
            if resp.content_type == "application/json":
                return resp.status, await resp.json()
            return resp.status, await resp.text()
        return resp.status, None


async def docker_api_post(endpoint: str, json_data: dict | None = None) -> tuple[int, Any]:
    async with (
        get_docker_session() as session,
        session.post(f"http://localhost{endpoint}", json=json_data) as resp,
    ):
        if resp.status in (200, 201):
            if resp.content_type == "application/json":
                return resp.status, await resp.json()
            return resp.status, await resp.text()
        return resp.status, None


async def fetch_container_info(container_name: str) -> dict[str, Any]:
    port = 8000
    model_id = container_name
    enforce_eager = False

    try:
        status, data = await docker_api_get(f"/containers/{container_name}/json")
        if status == 200 and data:
            config = data.get("Config", {})
            labels = config.get("Labels", {})

            # Label check
            if "sparkrun.role" in labels:
                model_id = labels["sparkrun.role"]

            # Network Port detection
            network_settings = data.get("NetworkSettings", {})
            ports_config = network_settings.get("Ports", {})
            if ports_config:
                for port_str in ports_config:
                    if "/tcp" in port_str:
                        port = int(port_str.split("/")[0])
                        break

            # Env check
            envs = config.get("Env", [])
            for env in envs:
                if env.startswith("VLLM_PORT="):
                    port = int(env.split("=")[1])
                if env == "VLLM_ENFORCE_EAGER=1":
                    enforce_eager = True

            # Cmd check
            cmd = config.get("Cmd", [])
            cmd_str = " ".join(cmd)
            port_match = re.search(r"--port\s+(\d+)", cmd_str)
            if port_match:
                port = int(port_match.group(1))
            model_match = re.search(
                r"(?:vllm serve|sglang\.launch_server\s+--model-path)\s+(\S+)", cmd_str
            )
            if model_match:
                model_id = model_match.group(1).lower().split("/")[-1]
            if "--enforce-eager" in cmd_str.lower() or "cuda_graph=false" in cmd_str.lower():
                enforce_eager = True

    except Exception as e:
        logger.exception(f"Error fetching info for {container_name}: {e}")

    logger.debug(
        f"Discovery: {container_name} resolved to '{model_id}' on port {port} (Eager: {enforce_eager})"
    )
    return {"port": port, "model_id": model_id, "enforce_eager": enforce_eager}


async def read_docker_stream(resp: aiohttp.ClientResponse) -> AsyncGenerator[str, None]:
    while True:
        try:
            header = await resp.content.readexactly(8)
            payload_len = int.from_bytes(header[4:8], "big")
            if payload_len == 0:
                continue
            payload = await resp.content.readexactly(payload_len)
            yield payload.decode("utf-8", "ignore")
        except asyncio.IncompleteReadError:
            break
        except Exception as e:
            logger.debug(f"Stream read error: {e}")
            break


async def log_tailer_task(container_name: str, info: dict) -> None:
    enforce_eager = info.get("enforce_eager", False)

    # Use a long timeout for log streaming
    timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=3600)

    while True:
        try:
            use_internal_log = False
            try:
                # Check for sparkrun log redirection
                status, data = await docker_api_post(
                    f"/containers/{container_name}/exec",
                    json_data={
                        "Cmd": ["test", "-f", "/tmp/sparkrun_serve.log"],
                        "AttachStdout": True,
                    },
                )
                if status == 201:
                    use_internal_log = True
            except Exception:
                pass

            if use_internal_log:
                logger.info(f"[{container_name}] Using internal log file /tmp/sparkrun_serve.log")
                status, data = await docker_api_post(
                    f"/containers/{container_name}/exec",
                    json_data={
                        "Cmd": ["tail", "-c", "+0", "-f", "/tmp/sparkrun_serve.log"],
                        "AttachStdout": True,
                        "AttachStderr": True,
                    },
                )
                if status == 201:
                    exec_id = data["Id"]
                    async with (
                        get_docker_session() as session,
                        session.post(
                            f"http://localhost/exec/{exec_id}/start", json={}, timeout=timeout
                        ) as resp,
                    ):
                        async for chunk in read_docker_stream(resp):
                            await process_log_chunk(container_name, chunk, enforce_eager)
            else:
                # Fallback to docker logs
                log_endpoint = (
                    f"/containers/{container_name}/logs?stdout=1&stderr=1&follow=1&tail=1000"
                )
                async with (
                    get_docker_session() as session,
                    session.get(f"http://localhost{log_endpoint}", timeout=timeout) as resp,
                ):
                    async for chunk in read_docker_stream(resp):
                        await process_log_chunk(container_name, chunk, enforce_eager)

            logger.warning(
                f"Log stream for {container_name} ended unexpectedly. Restarting in 1s..."
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Log tailer error for {container_name}: {e}. Retrying in 5s...")
            await asyncio.sleep(5.0)

        await asyncio.sleep(1.0)


async def process_log_chunk(container_name: str, chunk: str, enforce_eager: bool) -> None:
    phases = container_phases.setdefault(container_name, {"weights": 0, "compile": 0, "profile": 0})
    lines = chunk.splitlines()
    for line in lines:
        if not line.strip():
            continue

        if FATAL_REGEX.search(line):
            logger.error(f"Crash in {container_name}: {line.strip()}")
            last_known_pct[container_name] = -1
            last_known_phase[container_name] = "Crash"
            return

        if "Application startup complete" in line:
            logger.info(f"{container_name} reported startup complete via logs.")
            last_known_pct[container_name] = 100
            last_known_phase[container_name] = "Ready"
            return

        # Multi-Phase Blackwell/MTP Progress Logic
        pct = None
        phase = None
        if ARCHITECTURE_REGEX.search(line):
            pct = 2
            phase = "Resolving architecture"
        elif START_LOAD_REGEX.search(line):
            pct = 5
            phase = "Loading model weights"
        elif WEIGHTS_LOADED_REGEX.search(line):
            phases["weights"] += 1
            # Stage 1 (Base): 40%, Stage 2 (Drafter): 45%
            pct = 40 if phases["weights"] == 1 else 45
            phase = "Weights loaded"
        elif COMPILE_REGEX.search(line):
            phases["compile"] += 1
            # Stage 1 (Base): 80%, Stage 2 (Drafter): 85%
            pct = 80 if phases["compile"] == 1 else 85
            phase = "Compiling model"
        elif PROFILING_REGEX.search(line):
            phases["profile"] += 1
            # Stage 1 (Base): 95%, Stage 2 (Drafter): 99%
            pct = 95 if phases["profile"] == 1 else 99
            phase = "Profiling"

        if pct is not None:
            last_known_pct[container_name] = max(last_known_pct.get(container_name, 0), pct)
            if phase is not None:
                last_known_phase[container_name] = phase
            continue

        # Granular weight loading (INT4/FP4 shards)
        match_w_pct = PROGRESS_REGEX_PCT.search(line)
        if match_w_pct:
            val = int(match_w_pct.group(1))
            # Map 0-100% of weight load to the 5%-40% range for Phase 1
            pct = 5 + int(val * 0.35) if phases["weights"] == 0 else 40 + int(val * 0.05)
            phase = "Loading weights"
        else:
            match_w_frac = PROGRESS_REGEX_FRACT.search(line)
            if match_w_frac:
                cur, tot = int(match_w_frac.group("cur")), int(match_w_frac.group("tot"))
                if tot > 0:
                    val = int((cur / tot) * 100)
                    pct = 5 + int(val * 0.35) if phases["weights"] == 0 else 40 + int(val * 0.05)
                    phase = "Loading weights"

        if phase is not None:
            last_known_phase[container_name] = phase

        if pct is not None:
            last_known_pct[container_name] = max(last_known_pct.get(container_name, 0), pct)

        # CUDA Graph Progress (usually during compilation/warmup)
        match_cuda = CUDA_GRAPH_REGEX.search(line)
        if match_cuda:
            val = int(match_cuda.group(1))
            # Map to 50%-80% range
            pct = 50 + int(val * 0.30)
            phase = "Capturing CUDA graphs"
            last_known_pct[container_name] = max(last_known_pct.get(container_name, 0), pct)
            last_known_phase[container_name] = phase


async def check_readiness(url: str) -> bool:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(url, timeout=aiohttp.ClientTimeout(total=2.0)) as response,
        ):
            return response.status == 200
    except Exception:
        return False


async def readiness_poller_task(container_name: str, info: dict) -> None:
    target_url = f"http://{container_name}:{info['port']}/v1/models"
    logger.info(f"Monitoring {container_name} ({info['model_id']}) on {target_url}")

    ready = False
    try:
        while True:
            try:
                status, data = await docker_api_get(f"/containers/{container_name}/json")
                if status == 200 and data:
                    if not data.get("State", {}).get("Running", False):
                        last_known_pct[container_name] = -1
                        last_known_phase[container_name] = "Offline"
                        return
                else:
                    logger.debug(f"Poller: Container {container_name} info status {status}")
                    # Don't return immediately, retry
            except Exception as e:
                logger.debug(f"Poller error for {container_name}: {e}")

            if last_known_pct.get(container_name, 0) != -1:
                is_responsive = await check_readiness(target_url)
                if is_responsive:
                    last_known_pct[container_name] = 100
                    last_known_phase[container_name] = "Ready"
                    if not ready:
                        logger.success(f"{container_name} responded on {target_url}")
                        ready = True
                elif ready:
                    logger.warning(f"{container_name} became unresponsive.")
                    ready = False
                    last_known_pct[container_name] = 0
                    last_known_phase[container_name] = "Unresponsive"

            await asyncio.sleep(15.0 if ready else 5.0)
    except asyncio.CancelledError:
        pass


async def monitor_container_logic(container_name: str) -> None:
    info = await fetch_container_info(container_name)
    container_info_cache[container_name] = info
    last_known_pct.setdefault(container_name, 0)
    last_known_phase.setdefault(container_name, "Initializing...")

    tasks = [
        asyncio.create_task(log_tailer_task(container_name, info)),
        asyncio.create_task(readiness_poller_task(container_name, info)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except Exception:
        logger.exception(f"Monitor error in {container_name}")
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()


async def monitor_container(container_name: str) -> None:
    while True:
        await monitor_container_logic(container_name)
        status, data = await docker_api_get(f"/containers/{container_name}/json")
        if status != 200 or not data.get("State", {}).get("Running", False):
            break
        logger.warning(f"Connection to {container_name} lost. Re-monitoring in 5s...")
        await asyncio.sleep(5.0)


async def main() -> None:
    logger.info(f"Manager Protocol V2 starting (StatsD tcp: {STATSD_ADDR[0]}:{STATSD_ADDR[1]})")
    asyncio.create_task(run_api_server())
    asyncio.create_task(push_worker())

    while True:
        try:
            status, data = await docker_api_get(
                '/containers/json?filters={"label":["sparkrun.monitoring=true"]}'
            )
            if status == 200 and data is not None:
                containers = [c["Names"][0].lstrip("/") for c in data]
            else:
                containers = []

            for name in containers:
                if name not in active_monitors or active_monitors[name].done():
                    active_monitors[name] = asyncio.create_task(monitor_container(name))

            for name in list(active_monitors.keys()):
                if name not in containers:
                    if not active_monitors[name].done():
                        active_monitors[name].cancel()
                    del active_monitors[name]
                    if name in last_known_pct:
                        del last_known_pct[name]
                    if name in last_known_phase:
                        del last_known_phase[name]

        except Exception:
            logger.exception("Discovery API error")
        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
