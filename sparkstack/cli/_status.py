"""sparkstack status — live deployment monitor TUI.

Connects to the orchestrator's UNIX Domain Socket at /tmp/spark-stack.sock
and renders a live dashboard with service states and streaming logs.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

import click
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from . import main

SOCKET_PATH = "/tmp/spark-stack.sock"


@main.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show live deployment status and service health.

    Connects to the running orchestrator via UDS and displays
    a live-updating service dashboard with streaming logs.
    """
    from sparkstack.cli._common import run_async  # noqa: PLC0415

    run_async(_run_tui())


async def _run_tui() -> None:
    app = DeploymentMonitorApp()
    await app.run_async()


class ConnectionStatus(Static):
    """Shows the current socket connection state."""

    DEFAULT_CSS = """
    ConnectionStatus {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    """

    def update_status(self, connected: bool, message: str = "") -> None:
        if connected:
            self.update(f"[green]● Connected[/]  {message}")
        else:
            self.update(f"[red]● Disconnected[/]  {message}")


class DeploymentMonitorApp(App):
    """Textual TUI client for the sparkstack deployment orchestrator."""

    TITLE = "sparkstack status"
    SUB_TITLE = "Deployment Monitor"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "clear_log", "Clear log"),
    ]

    def __init__(self, auto_quit: bool = False, local_mode: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.auto_quit = auto_quit
        self.local_mode = local_mode

    CSS = """
    #dashboard {
        height: 1fr;
        min-height: 10;
    }
    #log-panel {
        height: 2fr;
        border-top: solid $accent;
    }
    DataTable {
        height: 100%;
    }
    RichLog {
        height: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        yield ConnectionStatus(id="conn-status")
        yield Vertical(
            DataTable(id="dashboard"),
            RichLog(id="log-panel", highlight=True, markup=True, wrap=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#dashboard", DataTable)
        table.add_column("Service", key="Service")
        table.add_column("Status", key="Status")
        table.add_column("Progress", key="Progress")
        table.add_column("Note", key="Note")
        if self.local_mode:
            self.query_one("#conn-status", ConnectionStatus).update_status(True, "Local Mode")
        else:
            self.query_one("#conn-status", ConnectionStatus).update_status(False, "Connecting...")
            self._connect_ipc()

    def feed_event(self, event_dict: dict) -> None:
        """Feed a dictionary event directly into the app (used for local mode)."""
        etype = event_dict.get("event_type")
        if etype == "state":
            self._handle_state_update(event_dict)
        elif etype == "full_sync":
            self._handle_full_sync(event_dict)
        elif etype == "log":
            log = self.query_one("#log-panel", RichLog)
            self._handle_log(event_dict, log)
        elif etype == "exit":
            log = self.query_one("#log-panel", RichLog)
            self._handle_exit(event_dict, log)

    def _handle_full_sync(self, event: dict) -> None:
        states = event.get("states", {})
        for _service_name, state_data in states.items():
            self._handle_state_update(state_data)

    def _handle_state_update(self, event: dict) -> None:
        table = self.query_one("#dashboard", DataTable)
        service = event.get("service")
        if not service:
            return

        status = event.get("status", "Unknown")
        progress = event.get("progress", 0.0)
        note = event.get("note", "")

        status_style = {
            "waiting": "dim",
            "running": "cyan",
            "complete": "bold green",
            "failed": "bold red",
        }.get(str(status).lower(), "white")

        formatted_status = f"[{status_style}]{status}[/]"
        progress_bar = f"{progress:.1f}%"

        try:
            table.update_cell(service, "Status", formatted_status)
            table.update_cell(service, "Progress", progress_bar)
            table.update_cell(service, "Note", str(note))
        except Exception:
            with suppress(Exception):
                table.add_row(service, formatted_status, progress_bar, str(note), key=service)

    @work(exclusive=True)
    async def _connect_ipc(self) -> None:
        """Connect to UDS and listen for events."""
        while self.is_running:
            try:
                reader, _ = await asyncio.open_unix_connection(SOCKET_PATH)
                self.query_one("#conn-status", ConnectionStatus).update_status(True)

                while self.is_running:
                    line = await reader.readline()
                    if not line:
                        break

                    try:
                        event = json.loads(line.decode().strip())
                        self.feed_event(event)
                    except json.JSONDecodeError:
                        continue

            except (FileNotFoundError, ConnectionRefusedError):
                self.query_one("#conn-status", ConnectionStatus).update_status(False, "Retrying...")
                await asyncio.sleep(1)
            except Exception as e:
                self.query_one("#conn-status", ConnectionStatus).update_status(False, f"Error: {e}")
                await asyncio.sleep(1)

    def _handle_log(self, event: dict, log: RichLog) -> None:
        level = event.get("level", "INFO")
        message = event.get("message", "")
        timestamp = event.get("timestamp", "")
        service = event.get("service")
        phase = event.get("phase")

        # Truncate ISO timestamp to HH:MM:SS
        time_short = timestamp[11:19] if len(timestamp) > 19 else timestamp

        level_style = {
            "DEBUG": "dim",
            "INFO": "cyan",
            "WARNING": "yellow",
            "ERROR": "red",
            "SUCCESS": "green",
            "PROGRESS": "bold magenta",
        }.get(level, "white")

        prefix = f"[dim]{time_short}[/]"
        if service:
            prefix += f" [blue]\\[{service}][/]"
        if phase is not None:
            prefix += f" [magenta](Phase {phase})[/]"

        log.write(f"{prefix} [{level_style}]{level:<8}[/] {message}")

    def _handle_exit(self, event: dict, log: RichLog) -> None:
        success = event.get("success", False)
        message = event.get("message", "")
        if success:
            log.write(f"\n[bold green]✨ {message}[/]")
        else:
            log.write(f"\n[bold red]❌ {message}[/]")

        if self.auto_quit:
            self.exit()
        else:
            log.write("[dim]Orchestrator finished. Press 'q' to quit.[/]")

    def action_clear_log(self) -> None:
        self.query_one("#log-panel", RichLog).clear()
