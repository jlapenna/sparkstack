#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import asyncio
import argparse
from pathlib import Path
import httpx
from loguru import logger
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    SpinnerColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
import sys

from tests.e2e.utils import get_active_services


async def wait_for_backends_to_load(stack_dir: Path, timeout: int = 1800) -> bool:
    services = await get_active_services(stack_dir)
    if not services:
        logger.error(f"❌ Failure: No active services discovered in '{stack_dir.name}/'")
        return False

    expected_containers = set()
    for svc in services:
        # Skip proxy gateway from progress monitoring
        if "gateway" in svc["name"]:
            continue
        target = svc.get("container") or svc["name"]
        expected_containers.add(target)

    if not expected_containers:
        logger.info("✅ Pass: No backends require loading")
        return True

    logger.info(f"Waiting for {len(expected_containers)} backend containers to be fully loaded...")

    all_ready = False
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
            tasks[c] = progress.add_task(
                f"Loading [cyan]{c}[/]", total=100, phase="[dim]Initializing...[/dim]"
            )

        async def poll_backend_status():
            nonlocal all_ready
            consecutive_errors = 0
            async with httpx.AsyncClient() as client:
                while True:
                    try:
                        res = await client.get("http://localhost:8126/status", timeout=2.0)
                        if res.status_code == 200:
                            consecutive_errors = 0
                            status_data = res.json()
                            all_ready = True
                            for c in expected_containers:
                                c_data = status_data.get(c, {})
                                if isinstance(c_data, dict):
                                    pct = c_data.get("pct", 0)
                                    phase = c_data.get("phase", "")
                                else:
                                    pct = c_data
                                    phase = ""

                                if pct == -1:
                                    print(f"\n❌ Failure: Fatal crash detected in backend {c}")
                                    progress.update(
                                        tasks[c],
                                        description=f"Loading [red]{c}[/] [FAILED]",
                                        phase="[red]Crash[/red]",
                                    )
                                    return False

                                # Handle normal progress
                                if pct >= 0:
                                    phase_fmt = (
                                        f"[blue]{phase}[/blue]"
                                        if phase
                                        else "[dim]Waiting...[/dim]"
                                    )
                                    progress.update(tasks[c], completed=pct, phase=phase_fmt)
                                    if pct < 100:
                                        all_ready = False

                            if all_ready:
                                return True
                    except httpx.RequestError:
                        all_ready = False
                        consecutive_errors += 1
                        if consecutive_errors >= 15:
                            logger.error(
                                "❌ Failure: Progress Manager at port 8126 is unreachable. Ensure 'monitoring' stack is up."
                            )
                            return False

                    await asyncio.sleep(2)

        try:
            result = await asyncio.wait_for(poll_backend_status(), timeout=timeout)
            if result is False:
                return False
        except TimeoutError:
            pass

    if all_ready:
        logger.info("✅ Pass: Backend Readiness (All models loaded)")
        return True
    else:
        logger.error("❌ Failure: Backend Readiness timed out")
        return False


# Layer 1 logic has been moved to tests/verify/test_wait_for_backends.py


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wait for backends in a stack to load.")
    parser.add_argument("--stack", help="Stack name to wait for (optional, defaults to 'current')")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent.absolute()
    stack_dir = root_dir / "spark-stack-registry" / "stacks" / args.stack if args.stack else root_dir / "current"

    try:
        if not asyncio.run(wait_for_backends_to_load(stack_dir, args.timeout)):
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n❌ Aborted by user.")
        sys.exit(1)
