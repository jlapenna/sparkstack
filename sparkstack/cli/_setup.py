"""Setup and configuration commands."""

import socket

import click

from sparkstack.core.env import (
    SPARKSTACK_HEADSCALE_AUTH_KEY,
    SPARKSTACK_HEADSCALE_SERVER,
    is_overlay_configured,
    set_env,
)
from sparkstack.manager.remote import get_headscale_auth_key, resolve_tailnet_ip

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
        click.echo(f"Saved SPARKSTACK_HEADSCALE_SERVER={headscale_server} to .env\n")
    else:
        click.echo(f"Headscale Control Plane: {headscale_server}")

    # 2. Ask to generate headscale keys if missing
    if not SPARKSTACK_HEADSCALE_AUTH_KEY:
        click.echo("\nNo Headscale auth key found in .env.")
        click.echo("Note: The 'sparkstack-headscale' container must be running to generate a key.")
        if click.confirm("Generate a new auth key and save it to .env?", default=True):
            await _setup_overlay_async()
    else:
        click.echo("\nHeadscale auth key is already configured.")
        if click.confirm("Regenerate auth key?", default=False):
            await _setup_overlay_async()

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
    click.echo("Configuring Headscale overlay network...")

    try:
        click.echo("Generating Headscale auth key...")
        auth_key = await get_headscale_auth_key()
        click.echo(f"Generated auth key: {auth_key[:8]}...")
        set_env("SPARKSTACK_HEADSCALE_AUTH_KEY", auth_key)
        click.echo("Saved SPARKSTACK_HEADSCALE_AUTH_KEY to .env")
    except Exception as e:
        click.secho(f"Failed to generate auth key: {e}", fg="red")
        click.echo("Make sure the sparkstack-headscale container is running (e.g. sparkstack update headscale).")
        return

    try:
        click.echo("Resolving Head sidecar Tailnet IP...")
        ip = await resolve_tailnet_ip("sparkstack-head-sidecar")
        set_env("SPARKSTACK_HEAD_TAILNET_IP", ip)
        click.echo(f"Saved SPARKSTACK_HEAD_TAILNET_IP ({ip}) to .env")
    except Exception as e:
        click.secho(f"Failed to resolve Tailnet IP: {e}", fg="yellow")
        click.echo("Make sure the sparkstack-head-sidecar container is running.")
