#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
from loguru import logger
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from sparkstack.core.discovery import get_active_services
from sparkstack.core.env import SPARK_NODE_TARGET, WORKER_TAILNET_IP
from sparkstack.core.ipc_server import IPCServer, StateUpdateEvent
from sparkstack.core.utils import async_run_command


@dataclass
class BackendStatusUpdate:
    container: str
    pct: int
    phase: str
    is_crash: bool = False
    error_msg: str | None = None
    logs: str | None = None


class BackendProbe:
    def __init__(
        self,
        expected_containers: set[str],
        fail_fast: bool = True,
        target_host: str = "localhost",
        env: dict[str, str] | None = None,
        services_by_container: dict[str, dict] | None = None,
    ):
        self.expected_containers = expected_containers
        self.fail_fast = fail_fast
        self.target_host = target_host
        self.env = env
        # Maps container name → service info dict (includes is_remote, target_host).
        self.services_by_container: dict[str, dict] = services_by_container or {}

    async def poll(self) -> AsyncIterator[BackendStatusUpdate]:
        all_ready = False
        async with httpx.AsyncClient() as client:
            while not all_ready:
                try:
                    res = await client.get(f"http://{self.target_host}:8126/status", timeout=2.0)
                    if res.status_code == 200:
                        status_data = res.json()
                        all_ready = True
                        for c in self.expected_containers:
                            c_data = {}
                            if c in status_data:
                                c_data = status_data[c]
                            else:
                                for node_data in status_data.values():
                                    if isinstance(node_data, dict) and c in node_data:
                                        c_data = node_data[c]
                                        break

                            if isinstance(c_data, dict):
                                pct = c_data.get("pct", 0)
                                phase = c_data.get("phase", "")
                                is_crash = c_data.get("is_crash", False)
                            else:
                                pct = c_data
                                phase = ""
                                is_crash = False

                            if is_crash:
                                logs = ""
                                svc_info = self.services_by_container.get(c, {})
                                if svc_info.get("is_remote") and svc_info.get("target_host"):
                                    # Remote backend: fetch logs via SSH.
                                    from sparkstack.manager.remote import (  # noqa: PLC0415
                                        run_ssh_command,
                                    )

                                    ssh_target = svc_info["target_host"]
                                    try:
                                        logs = await run_ssh_command(
                                            ssh_target,
                                            f"docker logs --tail 20 {c}",
                                            timeout=15,
                                        )
                                    except Exception as e:
                                        logs = f"Failed to fetch remote logs from {ssh_target}: {e}"
                                else:
                                    # Local backend: use local docker logs.
                                    try:
                                        res = await async_run_command(
                                            ["docker", "logs", "--tail", "20", c],
                                            check=False,
                                            env=self.env,
                                        )
                                        logs = res.stdout + res.stderr
                                    except Exception as e:
                                        logs = f"Failed to fetch logs: {e}"
                                yield BackendStatusUpdate(
                                    container=c, pct=-1, phase="Crash", is_crash=True, logs=logs
                                )
                                if self.fail_fast:
                                    return
                                all_ready = False
                                continue

                            if pct >= 0:
                                yield BackendStatusUpdate(container=c, pct=pct, phase=phase)
                                if pct < 100:
                                    all_ready = False
                except httpx.RequestError:
                    all_ready = False
                    # We continue looping and let the outer timeout handle failure, removing the premature 30s abort limit.

                if all_ready:
                    break
                await asyncio.sleep(2)


async def _smoke_test_direct(
    container: str, port: int, model_id: str, env: dict[str, str] | None = None
) -> bool | None:
    """Test a backend directly via docker exec, bypassing the LiteLLM gateway.

    Returns ``True`` on success, ``None`` on failure (the caller treats
    ``None`` as a signal to abort the entire smoke-test run).
    """
    # json imported at module level

    if "embedding" in model_id:
        payload = json.dumps({"model": model_id, "input": "Say hi"})
        endpoint = "embeddings"
    else:
        payload = json.dumps(
            {
                "model": model_id,
                "messages": [{"role": "user", "content": "Say hi"}],
                "max_tokens": 5,
            }
        )
        endpoint = "chat/completions"

    script = (
        "import urllib.request, json, sys; "
        f"req = urllib.request.Request('http://localhost:{port}/v1/{endpoint}', "
        f"data={payload!r}.encode(), "
        "headers={'Content-Type': 'application/json'}); "
        "resp = urllib.request.urlopen(req, timeout=180); "
        "print(resp.status)"
    )
    cmd = ["docker", "exec", container, "python3", "-c", script]
    try:
        result = await asyncio.wait_for(async_run_command(cmd, check=False, env=env), timeout=200)
        stdout = result.stdout.strip()
        if stdout == "200":
            logger.info(f"✅ Smoke test passed for {container} (direct)")
            return True
        logger.error(
            f"❌ Direct smoke test failed for {container}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        return None
    except Exception as e:
        logger.error(f"❌ Direct smoke test error for {container}: {e}")
        return None


async def wait_for_backends_to_load(
    stack_dir: Path,
    timeout: int = 1800,
    fail_fast: bool = True,
    ipc_server: IPCServer | None = None,
    output_json: bool = False,
) -> bool:
    services = await get_active_services(stack_dir)
    if not services:
        logger.error(f"❌ Failure: No active services discovered in '{stack_dir.name}/'")
        return False

    expected_containers = set()
    container_to_name = {}
    for svc in services:
        # Skip proxy gateway from progress monitoring
        if "gateway" in svc["name"] or "litellm" in svc["name"]:
            continue
        target = svc.get("container") or svc["name"]
        expected_containers.add(target)
        container_to_name[target] = svc["name"]

    if not expected_containers:
        logger.info("✅ Pass: No backends require loading")
        return True

    if not output_json:
        logger.info(
            f"Waiting for {len(expected_containers)} backend containers to be fully loaded..."
        )

    env = os.environ.copy()
    if SPARK_NODE_TARGET:
        if "://" in SPARK_NODE_TARGET:
            env["DOCKER_HOST"] = SPARK_NODE_TARGET
        else:
            env["DOCKER_CONTEXT"] = SPARK_NODE_TARGET

    # The vllm-progress-manager always runs on the Head node, mapping port 8126 locally
    target_host = "localhost"

    # Build a map of container → service info for remote-aware crash log retrieval.
    services_by_container: dict[str, dict] = {
        svc.get("container", svc["name"]): svc
        for svc in services
        if svc.get("container") or svc.get("name")
    }

    probe = BackendProbe(
        expected_containers,
        fail_fast=fail_fast,
        target_host=target_host,
        env=env,
        services_by_container=services_by_container,
    )

    # Use a dummy Progress context if output_json is True to keep the code clean
    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        TextColumn("[progress.description]{task.fields[phase]}"),
        disable=output_json,
    ) as progress:
        tasks = {}
        for c in expected_containers:
            display_name = str(container_to_name.get(c) or c)
            tasks[c] = progress.add_task(
                f"Loading [cyan]{display_name}[/]", total=100, phase="[dim]Initializing...[/dim]"
            )
            if ipc_server:
                ipc_server.update_state(
                    StateUpdateEvent(
                        service=display_name, status="Loading", progress=0.0, note="Initializing..."
                    )
                )

        async def poll_ui():
            async for update in probe.poll():
                display_name = str(container_to_name.get(update.container) or update.container)

                if output_json:
                    logger.info(
                        f"Progress: {display_name} {update.pct}% ({update.phase})",
                        service=display_name,
                        progress=update.pct,
                        phase=update.phase,
                    )

                if update.is_crash:
                    if ipc_server:
                        ipc_server.update_state(
                            StateUpdateEvent(
                                service=display_name, status="Failed", progress=0.0, note="Crash"
                            )
                        )
                    if fail_fast:
                        if not output_json:
                            print(
                                f"\n❌ Failure: Fatal crash detected in backend {update.container}"
                            )
                            progress.update(
                                tasks[update.container],
                                description=f"Loading [red]{update.container}[/] [FAILED]",
                                phase="[red]Crash[/red]",
                            )
                            print(f"\n--- Last 20 lines of {update.container} logs ---")
                            print(update.logs)
                            print("----------------------------------\n")
                        else:
                            logger.error(f"Fatal crash in {update.container}: {update.logs}")
                        return False

                    progress.update(
                        tasks[update.container],
                        description=f"Loading [red]{update.container}[/] [FAILED]",
                        phase="[red]Crash[/red]",
                    )
                    continue

                if update.error_msg:
                    logger.error(update.error_msg)
                    if fail_fast:
                        return False
                    continue

                phase_fmt = (
                    f"[blue]{update.phase}[/blue]" if update.phase else "[dim]Waiting...[/dim]"
                )
                progress.update(tasks[update.container], completed=update.pct, phase=phase_fmt)
                if ipc_server:
                    ipc_server.update_state(
                        StateUpdateEvent(
                            service=display_name,
                            status="Loading",
                            progress=float(update.pct),
                            note=update.phase or "Waiting...",
                        )
                    )
            return True

        result = False
        try:
            result = await asyncio.wait_for(poll_ui(), timeout=timeout)
            if result is False:
                return False
        except TimeoutError:
            pass

    if result:
        logger.info("✅ Pass: Backend Readiness (All models loaded)")
        if ipc_server:
            for c in expected_containers:
                display_name = str(container_to_name.get(c) or c)
                ipc_server.update_state(
                    StateUpdateEvent(
                        service=display_name, status="Complete", progress=100.0, note="Loaded"
                    )
                )
        logger.info("Running post-load smoke tests...")

        # Post-Load Smoke Test
        api_key = os.getenv("LITELLM_MASTER_KEY", "")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        litellm_port = os.getenv("VLLM_PORT", "4000")

        for svc in services:
            if svc.get("type") == "sparkrun" and svc.get("port"):
                port = svc["port"]
                container = svc.get("container", f"port-{port}")
                logger.info(
                    f"Smoke testing backend {container} via gateway on port {litellm_port}..."
                )
                try:
                    async with httpx.AsyncClient() as client:
                        model_id = svc.get("name", "").replace("backend:", "")
                        if not model_id:
                            logger.error(
                                f"❌ Smoke test failed: Could not determine model_id for {container}"
                            )
                            return False

                        if "embedding" in model_id:
                            res = await client.post(
                                f"http://{target_host}:{litellm_port}/v1/embeddings",
                                headers=headers,
                                json={"model": model_id, "input": "Say hi"},
                                timeout=180.0,
                            )
                        else:
                            res = await client.post(
                                f"http://{target_host}:{litellm_port}/v1/chat/completions",
                                headers=headers,
                                json={
                                    "model": model_id,
                                    "messages": [{"role": "user", "content": "Say hi"}],
                                    "max_tokens": 5,
                                },
                                timeout=180.0,
                            )

                        # If LiteLLM has no DB, bearer auth fails with
                        # "no_db_connection".  Fall back to testing the backend
                        # directly via docker exec (ports are internal-only).
                        if res.status_code != 200 and "no_db_connection" in res.text:
                            logger.warning(
                                f"Gateway has no DB for {container}, "
                                "falling back to direct backend smoke test..."
                            )
                            res = await _smoke_test_direct(container, port, model_id, env=env)
                            if res is None:
                                return False
                            continue

                        if res.status_code == 200:
                            logger.info(f"✅ Smoke test passed for {container}")
                        else:
                            logger.error(
                                f"❌ Smoke test inference failed for {container}: {res.text}"
                            )
                            return False
                except Exception as e:
                    logger.error(f"❌ Smoke test request failed for {container}: {e}")
                    return False
        return True
    logger.error("❌ Failure: Backend Readiness timed out")
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for backends in a stack to load.")
    parser.add_argument("--stack", help="Stack name to wait for (optional, defaults to 'current')")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    parser.add_argument(
        "--no-fail-fast", action="store_true", help="Monitor mode: do not exit on crash"
    )
    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent.absolute()
    stack_dir = (
        root_dir / "sparkstack-registry" / "stacks" / args.stack
        if args.stack
        else (root_dir / "current").resolve()
    )

    try:
        if not asyncio.run(
            wait_for_backends_to_load(stack_dir, args.timeout, fail_fast=not args.no_fail_fast)
        ):
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n❌ Aborted by user.")
        sys.exit(1)
