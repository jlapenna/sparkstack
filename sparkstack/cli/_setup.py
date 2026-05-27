import os
import socket

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from sparkstack.core.env import (
    SPARKSTACK_HEADSCALE_AUTH_KEY,
    SPARKSTACK_HEADSCALE_SERVER,
    is_overlay_configured,
    set_env,
)
from sparkstack.manager.remote import get_headscale_auth_key, resolve_head_tailnet_ip

from . import main
from ._common import run_async


@main.group(name="setup", invoke_without_command=True)
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Setup and configuration commands."""
    if ctx.invoked_subcommand is not None:
        return
    # Smart routing: auto-launch wizard when not fully configured
    if not is_overlay_configured() or not SPARKSTACK_HEADSCALE_AUTH_KEY:
        ctx.invoke(setup_wizard)
    else:
        click.echo(ctx.get_help())


@setup.command(name="wizard")
@click.pass_context
def setup_wizard(ctx: click.Context) -> None:
    """Guided setup wizard for sparkstack.

    Walks through Headscale overlay network configuration.
    """
    run_async(_setup_wizard_async())


async def _setup_wizard_async() -> None:
    click.echo()
    click.echo("Welcome to sparkstack setup wizard!")
    click.echo("=" * 48)
    click.echo()

    click.echo("Phase 1: Headscale Overlay Configuration")
    click.echo("-" * 30)

    # 1. Ask for Headscale server IP if not configured
    headscale_server = SPARKSTACK_HEADSCALE_SERVER
    if not headscale_server:
        try:
            # Try to guess local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            default_ip = s.getsockname()[0]
            s.close()
        except Exception:
            default_ip = "127.0.0.1"

        headscale_server = click.prompt(
            "Enter Headscale Control Plane IP/Domain", default=default_ip
        )
        set_env("SPARKSTACK_HEADSCALE_SERVER", headscale_server)
        click.echo(f"Saved SPARKSTACK_HEADSCALE_SERVER={headscale_server} to configuration\n")
    else:
        click.echo(f"Headscale Control Plane: {headscale_server}")

    # 2. Ask to generate headscale keys if missing
    if not SPARKSTACK_HEADSCALE_AUTH_KEY:
        click.echo("\nNo Headscale auth key found in configuration.")
        click.echo("Note: The 'sparkstack-headscale' container must be running to generate a key.")
        if click.confirm("Generate a new auth key and save it to configuration?", default=True):
            await _setup_overlay_async()
    else:
        click.echo("\nHeadscale auth key is already configured.")
        if click.confirm("Regenerate auth key?", default=False):
            await _setup_overlay_async()

    # Phase 2: Service & Feature Selection
    click.echo("\nPhase 2: Service & Feature Selection")
    click.echo("-" * 30)

    console = Console()

    services = [
        {"key": "SparkRun", "desc": "Base automated orchestration and evaluation framework."},
        {"key": "Cloudflare", "desc": "Secure external tunnel mapping (for WAN access)."},
        {"key": "Headscale", "desc": "Encrypted multi-node WireGuard overlay mesh network."},
        {
            "key": "InferenceStack",
            "desc": "High-throughput LLM inference engines (vLLM + LiteLLM).",
        },
        {
            "key": "RegistrySync",
            "desc": "Syncing model configurations and stacks into OpenClaw/LiteLLM.",
        },
        {
            "key": "Monitoring",
            "desc": "Real-time stack telemetry (Prometheus, Grafana, Alloy, Tempo).",
        },
        {"key": "OpenClaw", "desc": "AI Gateway and secure sandbox routing engine."},
    ]

    enabled_str = os.environ.get("SPARKSTACK_ENABLED_SERVICES")
    if enabled_str is not None:
        enabled_keys = {s.strip().lower() for s in enabled_str.split(",") if s.strip()}
    else:
        # Default all to enabled if not configured yet
        enabled_keys = {s["key"].lower() for s in services}

    while True:
        table = Table(
            title="Select Stack Services to Enable/Disable",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Index", style="cyan", justify="right")
        table.add_column("Status", justify="center")
        table.add_column("Service", style="bold green")
        table.add_column("Description", style="white")

        for idx, svc in enumerate(services, 1):
            is_enabled = svc["key"].lower() in enabled_keys
            status_text = (
                Text("✔", style="bold green") if is_enabled else Text("☐", style="dim red")
            )
            table.add_row(
                str(idx), status_text, svc["key"], svc["desc"], style=None if is_enabled else "dim"
            )

        console.print(table)
        console.print(
            "[dim]Enter index numbers separated by spaces/commas to toggle services (e.g. '2 6'), or press [bold green]Enter[/bold green] to confirm and proceed.[/dim]"
        )

        choice = Prompt.ask(
            "Selection (indices or Enter to confirm)", default="", show_default=False
        )
        if not choice.strip():
            break

        try:
            indices = [int(x.strip()) for x in choice.replace(",", " ").split() if x.strip()]
            for index in indices:
                if 1 <= index <= len(services):
                    svc_key = services[index - 1]["key"].lower()
                    if svc_key in enabled_keys:
                        enabled_keys.remove(svc_key)
                    else:
                        enabled_keys.add(svc_key)
                else:
                    console.print(f"[bold red]Invalid index: {index}[/bold red]")
        except ValueError:
            console.print(
                "[bold red]Please enter valid numbers (e.g. 2, 6) or press Enter.[/bold red]"
            )

    chosen_services = [svc["key"] for svc in services if svc["key"].lower() in enabled_keys]
    set_env("SPARKSTACK_ENABLED_SERVICES", ",".join(chosen_services))
    console.print(
        Panel(
            f"[bold green]Saved active services to configuration (sparkstack.yaml):[/bold green]\n"
            f"[cyan]SPARKSTACK_ENABLED_SERVICES={','.join(chosen_services)}[/cyan]",
            title="Configuration Saved",
            border_style="green",
        )
    )

    # Feature configuration - External Monitoring
    is_mon_enabled = any(s.lower() == "monitoring" for s in chosen_services)
    if is_mon_enabled:
        console.print("\n[bold cyan]Feature Configuration: Telemetry & Monitoring[/bold cyan]")
        use_external = click.confirm(
            "Do you want to use an external monitoring backend (Grafana/Prometheus/Tempo) instead of local deployment?",
            default=False,
        )
        if use_external:
            ext_host = click.prompt(
                "Enter external monitoring host IP or domain",
                default=os.environ.get("SPARK_MONITORING_HOST", ""),
            )
            set_env("SPARK_MONITORING_HOST", ext_host)
            console.print(
                f"[bold green]Saved SPARK_MONITORING_HOST={ext_host} to configuration (sparkstack.yaml)[/bold green]"
            )
        else:
            set_env("SPARK_MONITORING_HOST", "")
            console.print("[bold green]Configured monitoring to use local deployment.[/bold green]")

    # Feature configuration - Multi-Node Deployments
    console.print("\n[bold cyan]Feature Configuration: Multi-Node Remote Deployments[/bold cyan]")
    multi_node = click.confirm(
        "Do you want to configure remote node targets for multi-node deployment?", default=False
    )
    if multi_node:
        spark_node = click.prompt(
            "Enter Target remote node for Inference workers (Docker Context or SSH URI)",
            default=os.environ.get("SPARK_NODE_TARGET", ""),
        )
        openclaw_node = click.prompt(
            "Enter Target remote node for OpenClaw Gateway",
            default=os.environ.get("OPENCLAW_NODE_TARGET", ""),
        )
        monitoring_node = click.prompt(
            "Enter Target remote node for Monitoring stack",
            default=os.environ.get("MONITORING_NODE_TARGET", ""),
        )

        set_env("SPARK_NODE_TARGET", spark_node)
        set_env("OPENCLAW_NODE_TARGET", openclaw_node)
        set_env("MONITORING_NODE_TARGET", monitoring_node)

        console.print(
            "[bold green]Multi-node targets persisted to configuration (sparkstack.yaml)[/bold green]"
        )

        if (spark_node or openclaw_node or monitoring_node) and "Headscale" not in chosen_services:
            console.print(
                "[bold yellow]Multi-node deployment configured. Automatically enabling Headscale dependency...[/bold yellow]"
            )
            chosen_services.append("Headscale")
            set_env("SPARKSTACK_ENABLED_SERVICES", ",".join(chosen_services))
    else:
        # Clear them if they don't want remote
        set_env("SPARK_NODE_TARGET", "")
        set_env("OPENCLAW_NODE_TARGET", "")
        set_env("MONITORING_NODE_TARGET", "")
        console.print(
            "[bold green]Configured all services to deploy locally on the Head node.[/bold green]"
        )

    click.echo("\nSetup complete!")


@setup.command(name="overlay")
@click.pass_context
def setup_overlay(ctx: click.Context) -> None:
    """Generate and configure Headscale overlay keys and IPs.

    This command connects to the local sparkstack-headscale container to
    generate a pre-auth key, then connects to the head sidecar to resolve
    its Tailnet IP, saving both to the .env file.
    """
    run_async(_setup_overlay_async())


async def _setup_overlay_async() -> None:
    import asyncio  # noqa: PLC0415

    from sparkstack.core.env import PROJECT_ROOT  # noqa: PLC0415
    from sparkstack.core.utils import async_run_command  # noqa: PLC0415
    from sparkstack.manager.remote import deploy_head_sidecar  # noqa: PLC0415
    from sparkstack.manager.services import _render_headscale_config  # noqa: PLC0415

    click.echo("Configuring Headscale overlay network...")

    # 1. Ensure docker network sparkstack-net exists
    try:
        await async_run_command(
            ["docker", "network", "inspect", "sparkstack-net"],
            check=True,
            capture_output=True,
        )
    except Exception:
        click.echo("Creating external Docker network sparkstack-net...")
        try:
            await async_run_command(
                ["docker", "network", "create", "sparkstack-net"],
                check=True,
            )
        except Exception as e:
            click.secho(f"Failed to create sparkstack-net network: {e}", fg="red")
            return

    # 2. Render headscale configuration template
    hs_dir = PROJECT_ROOT / "services" / "headscale"
    click.echo("Rendering Headscale control plane configuration...")
    try:
        _render_headscale_config(hs_dir)
    except Exception as e:
        click.secho(f"Failed to render headscale configuration: {e}", fg="red")
        return

    # 3. Start headscale container
    click.echo("Deploying sparkstack-headscale container...")
    try:
        compose_cmd = [
            "docker",
            "compose",
            "-f",
            str(hs_dir / "docker-compose.yml"),
            "up",
            "-d",
            "--force-recreate",
        ]
        await async_run_command(compose_cmd, check=True)
    except Exception as e:
        click.secho(f"Failed to start headscale container: {e}", fg="red")
        return

    # 4. Wait for headscale container to become healthy
    click.echo("Waiting for Headscale control plane to become healthy...")
    for _ in range(30):
        try:
            res = await async_run_command(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", "sparkstack-headscale"],
                check=False,
                capture_output=True,
            )
            status = res.stdout.strip()
            if status == "healthy":
                click.echo("✅ Headscale control plane is healthy.")
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        click.secho(
            "⚠️ Headscale health check timed out, attempting to proceed anyway...", fg="yellow"
        )

    # 5. Generate pre-auth key
    try:
        click.echo("Generating Headscale auth key...")
        auth_key = await get_headscale_auth_key()
        click.echo(f"Generated auth key: {auth_key[:8]}...")
        set_env("SPARKSTACK_HEADSCALE_AUTH_KEY", auth_key)
        click.echo("Saved SPARKSTACK_HEADSCALE_AUTH_KEY to configuration (sparkstack.yaml)")
    except Exception as e:
        click.secho(f"Failed to generate auth key: {e}", fg="red")
        return

    # 6. Deploy head sidecar
    try:
        click.echo("Deploying local Head sidecar (sparkstack-head-sidecar)...")
        await deploy_head_sidecar()
    except Exception as e:
        click.secho(f"Failed to deploy Head sidecar: {e}", fg="red")
        return

    # 7. Resolve Tailnet IP
    try:
        click.echo("Resolving Head sidecar Tailnet IP...")
        ip = await resolve_head_tailnet_ip()
        set_env("SPARKSTACK_HEAD_TAILNET_IP", ip)
        click.echo(f"Saved SPARKSTACK_HEAD_TAILNET_IP ({ip}) to configuration (sparkstack.yaml)")
    except Exception as e:
        click.secho(f"Failed to resolve Tailnet IP: {e}", fg="red")
