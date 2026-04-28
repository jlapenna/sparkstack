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

from core.statsd import StatsdClient

# Configuration
STATSD_HOST = os.environ.get("SPARKRUN_STATSD_HOST", "vector")
STATSD_PORT = int(os.environ.get("SPARKRUN_STATSD_PORT", "8125"))
STATSD_ADDR = (STATSD_HOST, STATSD_PORT)
POLL_INTERVAL = 5.0
API_PORT = 8126

# Regex Compilations
FATAL_REGEX = re.compile(
    r"(?i)(?:AssertionError|RuntimeError|ValueError|error: argument|Exception:|Traceback|killed|Segmentation fault|Bus error|defunct|initialization failed|startup is less than desired)"
)
PROGRESS_REGEX_PCT = re.compile(r"(?i)(?:load|fetch|download).*?(\d{1,3})%")
PROGRESS_REGEX_FRACT = re.compile(r"(?i)(?:load|fetch).*?(?P<cur>\d+)\s*/\s*(?P<tot>\d+)")
CUDA_GRAPH_REGEX = re.compile(r"(?i)Capturing CUDA graphs.*?(\d{1,3})%")
ARCHITECTURE_REGEX = re.compile(r"(?i)Resolved architecture")
START_LOAD_REGEX = re.compile(r"(?i)Starting to load model")
WEIGHTS_LOADED_REGEX = re.compile(r"(?i)Loading weights took")
COMPILE_REGEX = re.compile(r"(?i)torch\.compile took")
PROFILING_REGEX = re.compile(r"(?i)Initial profiling/warmup")


statsd = StatsdClient(host=STATSD_HOST, port=STATSD_PORT, protocol="udp")


async def push_to_statsd(
    metric: str, value: int, container_name: str, model_id: str, host_id: str
) -> None:
    msg = f"{metric}:{value}|g|#name:{container_name},model_id:{model_id},host:{host_id}\n"
    await statsd.send(msg)


class DockerHostMonitor:
    def __init__(self, host_id: str, docker_url: str):
        self.host_id = host_id
        self.docker_url = docker_url

        if self.docker_url.startswith("unix://"):
            socket_path = self.docker_url.replace("unix://", "")
            self.connector = aiohttp.UnixConnector(path=socket_path)
            self.base_url = "http://localhost"
        elif self.docker_url.startswith("tcp://"):
            self.connector = aiohttp.TCPConnector()
            self.base_url = self.docker_url.replace("tcp://", "http://")
        else:
            self.connector = aiohttp.TCPConnector()
            self.base_url = self.docker_url

        self.session: aiohttp.ClientSession | None = None
        self.active_monitors: dict[str, asyncio.Task] = {}
        self.last_known_pct: dict[str, int] = {}
        self.last_known_phase: dict[str, str] = {}
        self.container_info_cache: dict[str, dict[str, Any]] = {}
        self.container_phases: dict[str, dict[str, int]] = {}
        self.running = False
        self.discovery_task: asyncio.Task | None = None
        self.push_task: asyncio.Task | None = None

    async def start(self):
        self.session = aiohttp.ClientSession(connector=self.connector)
        self.running = True
        self.discovery_task = asyncio.create_task(self.discovery_loop())
        self.push_task = asyncio.create_task(self.push_worker())
        logger.info(f"[{self.host_id}] Started monitor on {self.docker_url}")

    async def stop(self):
        self.running = False
        if self.discovery_task:
            self.discovery_task.cancel()
        if self.push_task:
            self.push_task.cancel()
        for t in self.active_monitors.values():
            t.cancel()
        if self.session:
            await self.session.close()
        logger.info(f"[{self.host_id}] Stopped monitor.")

    async def docker_api_get(self, endpoint: str, timeout: float = 2.0) -> tuple[int, Any]:
        if not self.session:
            return 500, None
        try:
            async with self.session.get(
                f"{self.base_url}{endpoint}", timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status == 200:
                    if "application/json" in resp.content_type:
                        return resp.status, await resp.json()
                    return resp.status, await resp.text()
                return resp.status, None
        except Exception as e:
            logger.debug(f"[{self.host_id}] docker_api_get error: {e}")
            return 500, None

    async def docker_api_post(
        self, endpoint: str, json_data: dict | None = None, timeout: float = 2.0
    ) -> tuple[int, Any]:
        if not self.session:
            return 500, None
        try:
            async with self.session.post(
                f"{self.base_url}{endpoint}",
                json=json_data,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status in (200, 201):
                    if "application/json" in resp.content_type:
                        return resp.status, await resp.json()
                    return resp.status, await resp.text()
                return resp.status, None
        except Exception as e:
            logger.debug(f"[{self.host_id}] docker_api_post error: {e}")
            return 500, None

    async def push_worker(self) -> None:
        while self.running:
            for container_name, pct in list(self.last_known_pct.items()):
                info = self.container_info_cache.get(container_name, {})
                model_id = info.get("model_id", container_name)
                await push_to_statsd(
                    "vllm_model_load_progress", pct, container_name, model_id, self.host_id
                )
            await asyncio.sleep(10.0)

    async def fetch_container_info(self, container_name: str) -> dict[str, Any]:
        port = 8000
        model_id = container_name
        enforce_eager = False

        try:
            status, data = await self.docker_api_get(f"/containers/{container_name}/json")
            if status == 200 and data:
                config = data.get("Config", {})
                labels = config.get("Labels", {})

                if "sparkrun.role" in labels:
                    model_id = labels["sparkrun.role"]

                network_settings = data.get("NetworkSettings", {})
                ports_config = network_settings.get("Ports", {})
                if ports_config:
                    for port_str in ports_config:
                        if "/tcp" in port_str:
                            port = int(port_str.split("/")[0])
                            break

                envs = config.get("Env", [])
                for env in envs:
                    if env.startswith("VLLM_PORT="):
                        port = int(env.split("=")[1])
                    if env == "VLLM_ENFORCE_EAGER=1":
                        enforce_eager = True

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
            logger.exception(f"[{self.host_id}] Error fetching info for {container_name}: {e}")

        logger.debug(
            f"[{self.host_id}] Discovery: {container_name} resolved to '{model_id}' on port {port} (Eager: {enforce_eager})"
        )
        return {"port": port, "model_id": model_id, "enforce_eager": enforce_eager}

    async def read_docker_stream(self, resp: aiohttp.ClientResponse) -> AsyncGenerator[str, None]:
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
                logger.debug(f"[{self.host_id}] Stream read error: {e}")
                break

    async def log_tailer_task(self, container_name: str, info: dict) -> None:
        enforce_eager = info.get("enforce_eager", False)
        # Use a long timeout for log streaming
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=3600)

        while self.running:
            try:
                use_internal_log = False
                try:
                    status, data = await self.docker_api_post(
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
                    logger.info(
                        f"[{self.host_id}|{container_name}] Using internal log file /tmp/sparkrun_serve.log"
                    )
                    status, data = await self.docker_api_post(
                        f"/containers/{container_name}/exec",
                        json_data={
                            "Cmd": ["tail", "-c", "+0", "-f", "/tmp/sparkrun_serve.log"],
                            "AttachStdout": True,
                            "AttachStderr": True,
                        },
                    )
                    if status == 201 and self.session is not None:
                        exec_id = data["Id"]
                        async with self.session.post(
                            f"{self.base_url}/exec/{exec_id}/start", json={}, timeout=timeout
                        ) as resp:
                            async for chunk in self.read_docker_stream(resp):
                                await self.process_log_chunk(container_name, chunk, enforce_eager)
                else:
                    log_endpoint = (
                        f"/containers/{container_name}/logs?stdout=1&stderr=1&follow=1&tail=1000"
                    )
                    if self.session is not None:
                        async with self.session.get(
                            f"{self.base_url}{log_endpoint}", timeout=timeout
                        ) as resp:
                            async for chunk in self.read_docker_stream(resp):
                                await self.process_log_chunk(container_name, chunk, enforce_eager)

                logger.warning(
                    f"[{self.host_id}] Log stream for {container_name} ended unexpectedly. Restarting in 1s..."
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    f"[{self.host_id}] Log tailer error for {container_name}: {e}. Retrying in 5s..."
                )
                await asyncio.sleep(5.0)

            await asyncio.sleep(1.0)

    async def process_log_chunk(self, container_name: str, chunk: str, enforce_eager: bool) -> None:
        phases = self.container_phases.setdefault(
            container_name, {"weights": 0, "compile": 0, "profile": 0}
        )
        lines = chunk.splitlines()
        for line in lines:
            if not line.strip():
                continue

            if FATAL_REGEX.search(line):
                logger.error(f"[{self.host_id}] Crash in {container_name}: {line.strip()}")
                self.last_known_pct[container_name] = -1
                self.last_known_phase[container_name] = "Crash"
                return

            if "Application startup complete" in line:
                logger.info(f"[{self.host_id}] {container_name} reported startup complete.")
                self.last_known_pct[container_name] = 100
                self.last_known_phase[container_name] = "Ready"
                return

            pct = None
            phase = None
            if ARCHITECTURE_REGEX.search(line):
                pct, phase = 2, "Resolving architecture"
            elif START_LOAD_REGEX.search(line):
                pct, phase = 5, "Loading model weights"
            elif WEIGHTS_LOADED_REGEX.search(line):
                phases["weights"] += 1
                pct = 40 if phases["weights"] == 1 else 45
                phase = "Weights loaded"
            elif COMPILE_REGEX.search(line):
                phases["compile"] += 1
                pct = 80 if phases["compile"] == 1 else 85
                phase = "Compiling model"
            elif PROFILING_REGEX.search(line):
                phases["profile"] += 1
                pct = 95 if phases["profile"] == 1 else 99
                phase = "Profiling"

            if pct is not None:
                self.last_known_pct[container_name] = max(
                    self.last_known_pct.get(container_name, 0), pct
                )
                if phase is not None:
                    self.last_known_phase[container_name] = phase
                continue

            match_w_pct = PROGRESS_REGEX_PCT.search(line)
            if match_w_pct:
                val = int(match_w_pct.group(1))
                pct = 5 + int(val * 0.35) if phases["weights"] == 0 else 40 + int(val * 0.05)
                phase = "Loading weights"
            else:
                match_w_frac = PROGRESS_REGEX_FRACT.search(line)
                if match_w_frac:
                    cur, tot = int(match_w_frac.group("cur")), int(match_w_frac.group("tot"))
                    if tot > 0:
                        val = int((cur / tot) * 100)
                        pct = (
                            5 + int(val * 0.35) if phases["weights"] == 0 else 40 + int(val * 0.05)
                        )
                        phase = "Loading weights"

            if phase is not None:
                self.last_known_phase[container_name] = phase

            if pct is not None:
                self.last_known_pct[container_name] = max(
                    self.last_known_pct.get(container_name, 0), pct
                )

            match_cuda = CUDA_GRAPH_REGEX.search(line)
            if match_cuda:
                val = int(match_cuda.group(1))
                pct = 50 + int(val * 0.30)
                phase = "Capturing CUDA graphs"
                self.last_known_pct[container_name] = max(
                    self.last_known_pct.get(container_name, 0), pct
                )
                self.last_known_phase[container_name] = phase

    async def readiness_poller_task(self, container_name: str, info: dict) -> None:
        logger.info(
            f"[{self.host_id}] Readiness poller started for {container_name} ({info['model_id']})"
        )
        ready = False
        try:
            while self.running:
                try:
                    status, data = await self.docker_api_get(f"/containers/{container_name}/json")
                    if status == 200 and data and not data.get("State", {}).get("Running", False):
                        self.last_known_pct[container_name] = -1
                        self.last_known_phase[container_name] = "Offline"
                        return
                except Exception as e:
                    logger.debug(f"[{self.host_id}] Poller error for {container_name}: {e}")

                if self.last_known_pct.get(container_name, 0) != -1:
                    # Exec into the container to curl its own port (avoiding external routing issues)
                    is_responsive = False
                    try:
                        status, data = await self.docker_api_post(
                            f"/containers/{container_name}/exec",
                            json_data={
                                "Cmd": [
                                    "curl",
                                    "-s",
                                    "-o",
                                    "/dev/null",
                                    "-w",
                                    "%{http_code}",
                                    f"http://127.0.0.1:{info['port']}/v1/models",
                                ],
                                "AttachStdout": True,
                            },
                        )
                        if status == 201 and self.session is not None:
                            exec_id = data["Id"]
                            async with self.session.post(
                                f"{self.base_url}/exec/{exec_id}/start", json={}
                            ) as resp:
                                output = await resp.text()
                                if "200" in output:
                                    is_responsive = True
                    except Exception:
                        pass

                    if is_responsive:
                        self.last_known_pct[container_name] = 100
                        self.last_known_phase[container_name] = "Ready"
                        if not ready:
                            logger.success(
                                f"[{self.host_id}] {container_name} readiness confirmed."
                            )
                            ready = True
                    elif ready:
                        logger.warning(f"[{self.host_id}] {container_name} became unresponsive.")
                        ready = False
                        self.last_known_pct[container_name] = 0
                        self.last_known_phase[container_name] = "Unresponsive"

                await asyncio.sleep(15.0 if ready else 5.0)
        except asyncio.CancelledError:
            pass

    async def monitor_container_logic(self, container_name: str) -> None:
        info = await self.fetch_container_info(container_name)
        self.container_info_cache[container_name] = info
        self.last_known_pct.setdefault(container_name, 0)
        self.last_known_phase.setdefault(container_name, "Initializing...")

        tasks = [
            asyncio.create_task(self.log_tailer_task(container_name, info)),
            asyncio.create_task(self.readiness_poller_task(container_name, info)),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except Exception:
            logger.exception(f"[{self.host_id}] Monitor error in {container_name}")
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    async def monitor_container(self, container_name: str) -> None:
        while self.running:
            await self.monitor_container_logic(container_name)
            status, data = await self.docker_api_get(f"/containers/{container_name}/json")
            if status != 200 or not data.get("State", {}).get("Running", False):
                break
            logger.warning(
                f"[{self.host_id}] Connection to {container_name} lost. Re-monitoring in 5s..."
            )
            await asyncio.sleep(5.0)

    async def discovery_loop(self) -> None:
        while self.running:
            try:
                status, data = await self.docker_api_get(
                    '/containers/json?filters={"label":["sparkrun.monitoring=true"]}'
                )
                if status == 200 and data is not None:
                    containers = [c["Names"][0].lstrip("/") for c in data]
                else:
                    containers = []

                for name in containers:
                    if name not in self.active_monitors or self.active_monitors[name].done():
                        self.active_monitors[name] = asyncio.create_task(
                            self.monitor_container(name)
                        )

                for name in list(self.active_monitors.keys()):
                    if name not in containers:
                        if not self.active_monitors[name].done():
                            self.active_monitors[name].cancel()
                        del self.active_monitors[name]
                        if name in self.last_known_pct:
                            del self.last_known_pct[name]
                        if name in self.last_known_phase:
                            del self.last_known_phase[name]

            except Exception as e:
                logger.error(f"[{self.host_id}] Discovery error: {e}")
            await asyncio.sleep(POLL_INTERVAL)


class FleetMultiplexer:
    def __init__(self):
        self.monitors: dict[str, DockerHostMonitor] = {}

    async def add_host(self, host_id: str, docker_url: str):
        if host_id in self.monitors:
            await self.monitors[host_id].stop()
        monitor = DockerHostMonitor(host_id, docker_url)
        self.monitors[host_id] = monitor
        await monitor.start()

    async def remove_host(self, host_id: str):
        if host_id in self.monitors:
            await self.monitors[host_id].stop()
            del self.monitors[host_id]

    async def handle_post_node(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            host_id = data.get("host_id")
            docker_url = data.get("docker_url")
            if not host_id or not docker_url:
                return web.json_response({"error": "Missing host_id or docker_url"}, status=400)

            await self.add_host(host_id, docker_url)
            return web.json_response({"status": "ok", "host_id": host_id, "docker_url": docker_url})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_delete_node(self, request: web.Request) -> web.Response:
        host_id = request.match_info.get("host_id")
        if not host_id:
            return web.json_response({"error": "Missing host_id"}, status=400)

        if host_id in self.monitors:
            await self.remove_host(host_id)
            return web.json_response({"status": "ok", "host_id": host_id, "action": "removed"})
        return web.json_response({"error": "Host not found"}, status=404)

    async def handle_api_request(self, request: web.Request) -> web.Response:
        res = {}
        for host_id, monitor in self.monitors.items():
            res[host_id] = {}
            for c, pct in monitor.last_known_pct.items():
                res[host_id][c] = {
                    "pct": pct,
                    "phase": monitor.last_known_phase.get(c, "Initializing...")
                    if pct >= 0
                    else "Failed",
                }
        return web.json_response(res)

    async def run_api_server(self) -> None:
        app = web.Application()
        app.router.add_get("/status", self.handle_api_request)
        app.router.add_post("/api/nodes", self.handle_post_node)
        app.router.add_delete("/api/nodes/{host_id}", self.handle_delete_node)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", API_PORT)
        logger.info(f"[Fleet] Fleet Multiplexer API listening on port {API_PORT}")
        await site.start()


async def main() -> None:
    logger.info(f"Fleet Multiplexer V3 starting (StatsD tcp: {STATSD_ADDR[0]}:{STATSD_ADDR[1]})")
    multiplexer = FleetMultiplexer()

    # Auto-register local docker socket as head-node
    await multiplexer.add_host("head-node", "unix:///var/run/docker.sock")

    await multiplexer.run_api_server()

    # Keep main alive
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
