"""sparkstack status — live deployment monitor TUI.

Connects to the orchestrator's UNIX Domain Socket at /tmp/spark-stack.sock
and renders a live dashboard with service states and streaming logs.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

import click
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from sparkstack.core.ipc_server import (
    ExitEvent,
    FullSyncEvent,
    IPCEvent,
    LogEvent,
    StateUpdateEvent,
    deserialize_event,
    event_adapter,
)

from . import main

logger = logging.getLogger(__name__)

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
        self._service_states: dict[str, StateUpdateEvent] = {}

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
        table.add_column("Updated", key="Updated")
        table.add_column("Note", key="Note")
        if self.local_mode:
            self.query_one("#conn-status", ConnectionStatus).update_status(True, "Local Mode")
        else:
            self.query_one("#conn-status", ConnectionStatus).update_status(False, "Connecting...")
            self._connect_ipc()

    def on_resize(self, event) -> None:
        self.call_after_refresh(self._resize_note_column)

    def _resize_note_column(self) -> None:
        try:
            table = self.query_one("#dashboard", DataTable)
            if "Note" not in table.columns:
                return

            other_width = 0
            for key, col in table.columns.items():
                if key != "Note":
                    other_width += col.get_render_width(table)

            # subtract from table's inner size width
            available = table.size.width - other_width - 2
            if available > 0:
                table.columns["Note"].width = available  # type: ignore
                table.columns["Note"].auto_width = False  # type: ignore
                table.refresh()
        except Exception:
            pass

    def feed_event(self, raw_event: IPCEvent | dict) -> None:
        """Feed an event directly into the app (used for local mode)."""
        if isinstance(raw_event, dict):
            try:
                event = event_adapter.validate_python(raw_event)
            except Exception:
                return
        else:
            event = raw_event

        if event.event_type == "state":
            self._handle_state_update(event)
        elif event.event_type == "full_sync":
            self._handle_full_sync(event)
        elif event.event_type == "log":
            self._handle_log(event)
        elif event.event_type == "exit":
            self._handle_exit(event)

    def _handle_full_sync(self, event: FullSyncEvent) -> None:
        # We no longer clear the table here, so stale/disconnected services remain visible (dimmed).
        for _service_name, state_data in event.states.items():
            self._handle_state_update(state_data)

    def _dim_all_rows(self) -> None:
        """Grey out all dashboard cells to indicate stale/disconnected data."""
        for state_event in self._service_states.values():
            with suppress(Exception):
                self._handle_state_update(state_event, dimmed=True)

    def _handle_state_update(self, event: StateUpdateEvent, dimmed: bool = False) -> None:
        table = self.query_one("#dashboard", DataTable)
        service = event.service
        if not service:
            return

        self._service_states[service] = event

        status = event.status or "Unknown"
        progress = event.progress or 0.0
        note = event.note or ""

        if not hasattr(self, "_service_timestamps"):
            self._service_timestamps = {}

        if not dimmed:
            self._service_timestamps[service] = datetime.now().strftime("%H:%M:%S")

        updated_time = self._service_timestamps.get(service, datetime.now().strftime("%H:%M:%S"))

        status_style = {
            "waiting": "dim",
            "running": "cyan",
            "complete": "bold green",
            "failed": "bold red",
        }.get(status.lower(), "white")

        def fmt(text: str, style: str = "") -> str:
            if not text:
                return ""
            if dimmed:
                return f"[dim]{text}[/]"
            return f"[{style}]{text}[/]" if style else text

        cells = {
            "Service": fmt(service),
            "Status": fmt(status, status_style),
            "Progress": fmt(f"{progress:.1f}%"),
            "Updated": fmt(updated_time),
            "Note": fmt(note),
        }

        if service in table.rows:
            for col_key, value in cells.items():
                table.update_cell(service, col_key, value, update_width=col_key != "Note")
        else:
            table.add_row(
                cells["Service"],
                cells["Status"],
                cells["Progress"],
                cells["Updated"],
                cells["Note"],
                key=service,
            )
        self._resize_note_column()

    @work(exclusive=True)
    async def _connect_ipc(self) -> None:
        """Connect to UDS and listen for events, auto-reconnecting on drops."""
        conn_status = self.query_one("#conn-status", ConnectionStatus)
        log_panel = self.query_one("#log-panel", RichLog)
        was_connected = False

        while self.is_running:
            try:
                reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)
                if was_connected:
                    conn_status.update_status(True, "Reconnected")
                    log_panel.write("[bold cyan]↻ Reconnected to orchestrator[/]")
                else:
                    conn_status.update_status(True)
                was_connected = True

                try:
                    while self.is_running:
                        line = await reader.readline()
                        if not line:
                            break  # EOF — orchestrator closed the connection

                        try:
                            event = deserialize_event(line)
                            self.feed_event(event)
                        except Exception:
                            logger.exception("Failed to deserialize or process IPC event")
                            continue
                finally:
                    writer.close()
                    with suppress(Exception):
                        await writer.wait_closed()

                # Connection dropped cleanly (EOF)
                self._on_disconnected(
                    conn_status, log_panel, "Orchestrator disconnected — waiting for reconnect…"
                )

            except (FileNotFoundError, ConnectionRefusedError):
                conn_status.update_status(False, "Waiting for orchestrator…")
            except Exception as e:
                conn_status.update_status(False, f"Error: {e}")

            await asyncio.sleep(2)

    def _on_disconnected(
        self, conn_status: ConnectionStatus, log_panel: RichLog, message: str
    ) -> None:
        """Handle a disconnection: update status, log it, and dim the dashboard."""
        conn_status.update_status(False, message)
        log_panel.write(f"[yellow]⚠ {message}[/]")
        with suppress(Exception):
            self._dim_all_rows()

    def _handle_log(self, event: LogEvent) -> None:
        level = event.level
        message = event.message
        timestamp = event.timestamp

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
        if event.service:
            prefix += f" [blue]\\[{event.service}][/]"
        if event.phase is not None:
            prefix += f" [magenta](Phase {event.phase})[/]"

        self.query_one("#log-panel", RichLog).write(
            f"{prefix} [{level_style}]{level:<8}[/] {message}"
        )

    def _handle_exit(self, event: ExitEvent) -> None:
        log = self.query_one("#log-panel", RichLog)
        if event.success:
            log.write(f"\n[bold green]✨ {event.message}[/]")
        else:
            log.write(f"\n[bold red]❌ {event.message}[/]")

        if self.auto_quit:
            self.exit()
        else:
            log.write("[dim]Orchestrator finished. Press 'q' to quit.[/]")

    def action_clear_log(self) -> None:
        self.query_one("#log-panel", RichLog).clear()
