"""sparkstack monitor \u2014 real-time service availability CLI."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click
import httpx
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, RichLog, Static

from sparkstack.core.discovery import get_active_services
from sparkstack.core.utils import async_run_command

from . import main
from ._common import resolve_stack_dir, run_async


@main.command("monitor")
@click.option("--stack", default=None, help="Stack to monitor (default: current).")
@click.option(
    "--interval", default=2.0, type=float, help="Polling interval in seconds (default: 2.0)."
)
@click.pass_context
def monitor(ctx: click.Context, stack: str | None, interval: float) -> None:
    """Show a real-time summary of all service availability."""
    stack_dir = resolve_stack_dir(stack)
    if not stack_dir.is_dir():
        raise click.BadParameter(f"Stack directory {stack_dir} does not exist.")
    run_async(_run_monitor(stack_dir, interval))


async def _run_monitor(stack_dir: Path, interval: float) -> None:
    app = MonitorApp(stack_dir=stack_dir, interval=interval)
    await app.run_async()


class ConnectionStatus(Static):
    """Shows the current monitoring state."""

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
            self.update(f"[green]\u25cf Active[/]  {message}")
        else:
            self.update(f"[red]\u25cf Offline[/]  {message}")


class MonitorApp(App):
    """Textual TUI for monitoring service availability."""

    TITLE = "sparkstack monitor"
    SUB_TITLE = "Real-time Service Availability"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("c", "clear_log", "Clear log"),
        ("y", "copy_row", "Copy Row"),
        ("l", "copy_logs", "Copy Logs"),
    ]

    CSS = """
    #dashboard {
        height: 1fr;
    }
    #detail-log {
        height: 1fr;
        border-top: solid $accent;
    }
    """

    def __init__(self, stack_dir: Path, interval: float = 2.0, **kwargs):
        super().__init__(**kwargs)
        self.stack_dir = stack_dir
        self.interval = interval
        self._service_containers: dict[str, str] = {}
        self.selected_service: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield ConnectionStatus(id="conn-status")
        yield Vertical(
            DataTable(id="dashboard", cursor_type="row"),
            RichLog(id="detail-log", highlight=True, markup=True, wrap=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#dashboard", DataTable)
        table.add_column("Service", key="Service")
        table.add_column("Type", key="Type")
        table.add_column("State", key="State")
        table.add_column("Health / Status", key="Status")
        self.query_one("#conn-status", ConnectionStatus).update_status(True, "Polling services...")
        self._poll_status()

    @work(exclusive=True)
    async def _poll_status(self) -> None:
        table = self.query_one("#dashboard", DataTable)

        while self.is_running:
            try:
                services = await get_active_services(self.stack_dir)
                docker_status = await self._get_docker_status()
                sparkrun_status = await self._get_sparkrun_status()
                openclaw_health = await self._get_openclaw_health()

                all_containers = set()

                current_keys = set()
                for svc in services:
                    container = svc.get("container") or svc.get("name", "")
                    svc_type = svc.get("type", "unknown")
                    name = str(svc.get("name", container))
                    d_data = None

                    state = "[dim]Unknown[/]"
                    status = ""

                    if svc_type == "sparkrun":
                        # Check sparkrun API for backend readiness
                        sr_data = sparkrun_status.get(container)
                        if sr_data:
                            phase = sr_data.get("phase", "")
                            pct = sr_data.get("pct", 0)
                            if sr_data.get("is_crash"):
                                state = "[bold red]Crash[/]"
                                status = phase
                            elif pct == 100:
                                state = "[bold green]Ready[/]"
                                status = "100%"
                            else:
                                state = "[cyan]Loading[/]"
                                status = f"{pct}% - {phase}"
                            d_data = self._find_docker_data(docker_status, container)
                        else:
                            # Fallback to docker
                            d_data = docker_status.get(container)
                            if d_data:
                                state = self._format_state(d_data.get("State", ""))
                                status = str(d_data.get("Status", ""))
                            else:
                                state = "[dim]Not Found[/]"
                    elif "openclaw" in name.lower() or "openclaw" in container.lower():
                        d_data = self._find_docker_data(docker_status, container)
                        if d_data:
                            state = self._format_state(d_data.get("State", ""))
                            # If we pinged the healthz endpoint and it's up, override or supplement
                            if openclaw_health:
                                status = f"API OK | {d_data.get('Status', '')}"
                            else:
                                status = str(d_data.get("Status", ""))
                        else:
                            state = "[dim]Not Found[/]"
                    else:
                        # Docker compose type or other
                        d_data = self._find_docker_data(docker_status, container)
                        if d_data:
                            state = self._format_state(d_data.get("State", ""))
                            status = str(d_data.get("Status", ""))
                        else:
                            state = "[dim]Not Found[/]"

                    self._update_row(table, name, svc_type, state, status)
                    current_keys.add(name)
                    actual_container = str(d_data.get("Names") if d_data else container)
                    self._service_containers[name] = actual_container
                    if d_data:
                        all_containers.add(actual_container)

                # Also include litellm, monitoring, openclaw stuff that we can identify globally
                for cname, cdata in docker_status.items():
                    if not cname:
                        continue
                    if cname in all_containers:
                        continue
                    if any(
                        keyword in str(cname).lower()
                        for keyword in [
                            "monitoring",
                            "tempo",
                            "alloy",
                            "grafana",
                            "prometheus",
                            "litellm",
                            "openclaw",
                        ]
                    ):
                        name = cname
                        svc_type = "infrastructure"
                        state = self._format_state(cdata.get("State", ""))
                        status = str(cdata.get("Status", ""))

                        if "openclaw" in str(cname).lower() and openclaw_health:
                            status = f"API OK | {status}"

                        self._update_row(table, name, svc_type, state, status)
                        current_keys.add(name)
                        self._service_containers[name] = name
                        all_containers.add(cname)

                # Remove stale rows
                keys_to_remove = []
                for row_key in table.rows:
                    if row_key.value not in current_keys:
                        keys_to_remove.append(row_key)
                for row_key in keys_to_remove:
                    table.remove_row(row_key)
                    if row_key.value in self._service_containers:
                        del self._service_containers[row_key.value]

            except Exception:
                pass

            if self.selected_service:
                await self._fetch_logs_impl(self.selected_service)

            await asyncio.sleep(self.interval)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_service = str(event.row_key.value)
        self.query_one("#detail-log", RichLog).clear()
        self.run_worker(self._fetch_logs_impl(self.selected_service), exclusive=True)

    async def _fetch_logs_impl(self, service_name: str) -> None:
        container = self._service_containers.get(service_name)
        log_panel = self.query_one("#detail-log", RichLog)

        if not container:
            return

        try:
            res = await async_run_command(
                ["docker", "logs", "--tail", "20", container], check=False
            )
            log_panel.clear()
            log_panel.write(f"[bold cyan]Logs for {container}[/]")
            if res.stdout:
                log_panel.write(res.stdout)
            if res.stderr:
                log_panel.write(res.stderr)
        except Exception as e:
            log_panel.clear()
            log_panel.write(f"[red]Failed to fetch logs: {e}[/]")

    def action_clear_log(self) -> None:
        self.query_one("#detail-log", RichLog).clear()

    def action_copy_row(self) -> None:
        table = self.query_one("#dashboard", DataTable)
        try:
            row_data = table.get_row_at(table.cursor_row)
        except Exception:
            self.notify("No row selected", severity="error")
            return

        plain_text_parts = []
        for cell in row_data:
            if isinstance(cell, str):
                plain_text_parts.append(Text.from_markup(cell).plain)
            else:
                plain_text_parts.append(str(cell))

        text = " | ".join(plain_text_parts)
        self.copy_to_clipboard(text)
        self.notify("Row copied to clipboard", timeout=2)

    def action_copy_logs(self) -> None:
        log_panel = self.query_one("#detail-log", RichLog)
        lines = []
        for line in log_panel.lines:
            if hasattr(line, "text"):
                lines.append(line.text)
            else:
                lines.append(str(line))
        text = "\n".join(lines)
        self.copy_to_clipboard(text)
        self.notify("Logs copied to clipboard", timeout=2)

    def _find_docker_data(self, docker_status: dict, name: str) -> dict | None:
        if name in docker_status:
            return docker_status[name]
        # try substring matching
        for cname, data in docker_status.items():
            if cname and name in cname:
                return data
        return None

    def _format_state(self, state: str) -> str:
        state_map = {
            "running": "[bold green]running[/]",
            "exited": "[bold red]exited[/]",
            "created": "[yellow]created[/]",
            "dead": "[bold red]dead[/]",
            "restarting": "[cyan]restarting[/]",
        }
        return state_map.get(state.lower(), state)

    def _update_row(
        self, table: DataTable, name: str, svc_type: str, state: str, status: str
    ) -> None:
        for k in table.rows:
            if k.value == name:
                table.update_cell(k, "Type", svc_type)
                table.update_cell(k, "State", state)
                table.update_cell(k, "Status", status)
                return
        table.add_row(name, svc_type, state, status, key=name)

    async def _get_docker_status(self) -> dict[str, dict]:
        try:
            res = await async_run_command(
                ["docker", "ps", "-a", "--format", "{{json .}}"], check=False
            )
            containers = {}
            for line in res.stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    names = data.get("Names", "")
                    containers[names] = data
                except json.JSONDecodeError:
                    continue
            return containers
        except Exception:
            return {}

    async def _get_sparkrun_status(self) -> dict[str, dict]:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("http://localhost:8126/status", timeout=2.0)
                if res.status_code == 200:
                    data = res.json()
                    flattened = {}
                    for node, containers in data.items():
                        if isinstance(containers, dict):
                            if "pct" in containers:
                                flattened[node] = containers
                            else:
                                for c_name, c_data in containers.items():
                                    flattened[c_name] = c_data
                        else:
                            flattened[node] = containers
                    return flattened
        except Exception:
            pass
        return {}

    async def _get_openclaw_health(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("http://localhost:18789/healthz", timeout=2.0)
                return res.status_code in (200, 204)
        except Exception:
            pass
        return False
