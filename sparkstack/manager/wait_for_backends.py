#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import argparse
import asyncio
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
    def __init__(self, expected_containers: set[str], fail_fast: bool = True):
        self.expected_containers = expected_containers
        self.fail_fast = fail_fast

    async def poll(self) -> AsyncIterator[BackendStatusUpdate]:
        all_ready = False
        async with httpx.AsyncClient() as client:
            while not all_ready:
                try:
                    res = await client.get("http://localhost:8126/status", timeout=2.0)
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
                                try:
                                    res = await async_run_command(
                                        ["docker", "logs", "--tail", "20", c],
                                        check=False,
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


async def wait_for_backends_to_load(
    stack_dir: Path,
    timeout: int = 1800,
    fail_fast: bool = True,
    ipc_server: IPCServer | None = None,
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

    logger.info(f"Waiting for {len(expected_containers)} backend containers to be fully loaded...")

    probe = BackendProbe(expected_containers, fail_fast=fail_fast)

    with Progress(
        SpinnerColumn("dots"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        TimeElapsedColumn(),
        TextColumn("[progress.description]{task.fields[phase]}"),
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
                if update.is_crash:
                    if ipc_server:
                        ipc_server.update_state(
                            StateUpdateEvent(
                                service=display_name, status="Failed", progress=0.0, note="Crash"
                            )
                        )
                    if fail_fast:
                        print(f"\n❌ Failure: Fatal crash detected in backend {update.container}")
                        progress.update(
                            tasks[update.container],
                            description=f"Loading [red]{update.container}[/] [FAILED]",
                            phase="[red]Crash[/red]",
                        )
                        print(f"\n--- Last 20 lines of {update.container} logs ---")
                        print(update.logs)
                        print("----------------------------------\n")
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

        for svc in services:
            if svc.get("type") == "sparkrun" and svc.get("port"):
                port = svc["port"]
                container = svc.get("container", f"port-{port}")
                logger.info(f"Smoke testing backend {container} directly on port {port}...")
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
                                "http://localhost:4000/v1/embeddings",
                                headers=headers,
                                json={"model": model_id, "input": "Say hi"},
                                timeout=180.0,
                            )
                        else:
                            res = await client.post(
                                "http://localhost:4000/v1/chat/completions",
                                headers=headers,
                                json={
                                    "model": model_id,
                                    "messages": [{"role": "user", "content": "Say hi"}],
                                    "max_tokens": 5,
                                },
                                timeout=180.0,
                            )
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
        root_dir / "spark-stack-registry" / "stacks" / args.stack
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
