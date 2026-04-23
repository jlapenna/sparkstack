#!/usr/bin/env -S uv run --env-file .env --frozen --offline python3
import sys
import argparse
import asyncio
import contextlib
import termios
import tty
from datetime import datetime
from enum import Enum
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.table import Table

from scripts.verify.context import VerifyContext
from scripts.verify import (
    memory_law,
    proxy_integrity,
    functional_embeddings,
    openclaw_diagnosis,
    consumer_readiness,
    telemetry_verification,
    reliability_verification,
    regression_testing,
    tool_calling_verification,
    outbound_network,
    workspace_io,
    tracing_verification,
    cloudflare,
    agent_skills,
)
from scripts.verify.utils import current_layer
from scripts import wait_for_backends


class CheckStatus(Enum):
    WAITING = "waiting"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class CheckState:
    def __init__(self, name: str):
        self.name = name
        self.status = CheckStatus.WAITING
        self.note = ""
        self.start_time = None

    def start(self):
        self.status = CheckStatus.RUNNING
        self.note = "Running..."
        self.start_time = datetime.now()

    def complete(self):
        self.status = CheckStatus.COMPLETE
        self.note = "Passed"

    def fail(self, msg: str | None = None):
        self.status = CheckStatus.FAILED
        if msg is not None:
            self.note = str(msg)
        elif self.note in ["Running...", "Pending", ""]:
            self.note = "Failed"


class VerifyOrchestrator:
    def __init__(self, check_names: list[str]):
        self.console = Console()
        self.states = {name: CheckState(name) for name in check_names}

    def render_table(self) -> Table:
        table = Table(
            title="[bold blue]E2E Verification Dashboard[/]", title_justify="left", expand=True
        )
        table.add_column("Layer", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center", min_width=18)
        table.add_column("Notes", style="dim", ratio=1, no_wrap=True, overflow="ellipsis")

        for name, state in self.states.items():
            status_color = {
                CheckStatus.WAITING: "white",
                CheckStatus.RUNNING: "yellow",
                CheckStatus.COMPLETE: "green",
                CheckStatus.FAILED: "red",
            }.get(state.status, "white")

            time_str = ""
            if state.start_time and state.status == CheckStatus.RUNNING:
                elapsed = (datetime.now() - state.start_time).total_seconds()
                time_str = f" [{elapsed:.1f}s]"

            note_str = state.note
            if not note_str and state.status == CheckStatus.WAITING:
                note_str = "Pending"

            table.add_row(
                name,
                f"[{status_color}]{state.status.value.capitalize()}{time_str}[/]",
                note_str,
            )
        return table


class StackVerifier:
    def __init__(self, stack_name: str | None = None):
        root_dir = Path(__file__).parent.parent.absolute()
        stack_dir = root_dir / "spark-stack-registry" / "stacks" / stack_name if stack_name else root_dir / "current"

        oc_bin = Path.home() / "bin" / "oc"
        gateway_url = "http://localhost:4000/v1"
        telemetry_url = "http://localhost:9090/api/v1/targets"

        self.ctx = VerifyContext(
            root_dir=root_dir,
            stack_dir=stack_dir,
            oc_bin=oc_bin,
            gateway_url=gateway_url,
            telemetry_url=telemetry_url,
        )

    async def run_check(self, name: str, coro, orchestrator: VerifyOrchestrator):
        current_layer.set(name)
        state = orchestrator.states[name]
        state.start()
        try:
            success = await coro
            if success:
                state.complete()
            else:
                state.fail()
            return success
        except Exception as e:
            state.fail(f"Exception: {e}")
            return False

    async def verify(self, run_soak: bool = False):
        console = Console()
        console.print(f"🔍 [bold]STARTING PRE-VERIFICATION CHECKS: {self.ctx.stack_dir.name}[/]")

        # Enable visible logging for pre-verification
        sys_logger = logger.add(sys.stderr, level="INFO")

        # Layer 0 & Layer 1 (Standalone checks before launching Dashboard)
        if not await memory_law.run(self.ctx):
            console.print("\n[bold red]💔 PRE-FLIGHT VERIFICATION FAILED AT MEMORY LAW[/]")
            return False

        if not await wait_for_backends.run(self.ctx):
            console.print("\n[bold red]💔 PRE-FLIGHT VERIFICATION FAILED AT BACKEND READINESS[/]")
            return False

        logger.remove(sys_logger)

        # Parallel Checks
        check_defs = [
            (proxy_integrity.run.layer_name, proxy_integrity.run(self.ctx)),
            (functional_embeddings.run.layer_name, functional_embeddings.run(self.ctx)),
            (openclaw_diagnosis.run.layer_name, openclaw_diagnosis.run(self.ctx)),
            (consumer_readiness.run.layer_name, consumer_readiness.run(self.ctx)),
            (telemetry_verification.run.layer_name, telemetry_verification.run(self.ctx)),
            (regression_testing.run.layer_name, regression_testing.run(self.ctx)),
            (tool_calling_verification.run.layer_name, tool_calling_verification.run(self.ctx)),
            (outbound_network.run.layer_name, outbound_network.run(self.ctx)),
            (workspace_io.run.layer_name, workspace_io.run(self.ctx)),
            (tracing_verification.run.layer_name, tracing_verification.run(self.ctx)),
            (cloudflare.run.layer_name, cloudflare.run(self.ctx)),
            (agent_skills.run.layer_name, agent_skills.run(self.ctx)),
            (
                reliability_verification.run.layer_name,
                reliability_verification.run(self.ctx, minutes=30 if run_soak else 2),
            ),
        ]

        orchestrator = VerifyOrchestrator([name for name, _ in check_defs])

        def ui_sink(msg):
            layer = current_layer.get()
            if layer and layer in orchestrator.states:
                text = msg.record["message"].split("\n")[0]
                orchestrator.states[layer].note = text

        ui_logger = logger.add(ui_sink, level="INFO")
        success = True

        @contextlib.contextmanager
        def prevent_tty_echo():
            if not sys.stdin.isatty():
                yield
                return
            fd = sys.stdin.fileno()
            old = None
            try:
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                yield
            except Exception:
                yield
            finally:
                if old is not None:
                    try:
                        termios.tcflush(fd, termios.TCIFLUSH)
                        termios.tcsetattr(fd, termios.TCSANOW, old)
                    except Exception:
                        pass

        with (
            prevent_tty_echo(),
            Live(
                orchestrator.render_table(), console=orchestrator.console, refresh_per_second=4
            ) as live,
        ):

            async def auto_refresh():
                while True:
                    live.update(orchestrator.render_table())
                    await asyncio.sleep(0.2)

            refresh_task = asyncio.create_task(auto_refresh())
            try:
                results = []
                for name, coro in check_defs:
                    result = await self.run_check(name, coro, orchestrator)
                    results.append(result)
                if not all(results):
                    success = False
            finally:
                refresh_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await refresh_task
                live.update(orchestrator.render_table())

        logger.remove(ui_logger)
        orchestrator.console.print(orchestrator.render_table())

        if success:
            orchestrator.console.print("\n[bold green]✨ ALL E2E VERIFICATION LAYERS PASSED[/]")
        else:
            orchestrator.console.print("\n[bold red]💔 VERIFICATION FAILED[/]")

        return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-end stack verification.")
    parser.add_argument("--stack", help="Stack name to verify (optional, defaults to 'current')")
    parser.add_argument(
        "--soak", action="store_true", help="Run the 30-minute reliability soak test"
    )
    args = parser.parse_args()

    # Route all normal file logging to verify.log silently
    logger.remove()
    logger.add("verify.log", level="DEBUG")

    if not asyncio.run(StackVerifier(stack_name=args.stack).verify(run_soak=args.soak)):
        sys.exit(1)
