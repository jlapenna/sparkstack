"""sparkstack CLI — manage the Spark AI services stack."""

from __future__ import annotations

import click

from sparkstack import __version__

from ._common import _setup_logging


@click.group()
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v info, -vv debug)")
@click.option("-q", "--quiet", is_flag=True, help="Suppress non-error output")
@click.version_option(__version__, prog_name="sparkstack")
@click.pass_context
def main(ctx: click.Context, verbose: int, quiet: bool) -> None:
    """sparkstack — Manage the Spark AI services stack."""
    ctx.ensure_object(dict)
    if quiet:
        verbose = -1
    ctx.obj["verbose"] = verbose
    _setup_logging(verbose)


# Import and register sub-commands.
from ._build import build  # noqa: E402, F401
from ._check import check  # noqa: E402, F401
from ._launch import launch  # noqa: E402, F401
from ._monitor import monitor  # noqa: E402, F401
from ._monitoring import update_monitoring  # noqa: E402, F401
from ._set_current import set_current  # noqa: E402, F401
from ._status import status  # noqa: E402, F401
from ._sync import sync_registry_cmd  # noqa: E402, F401
from ._sync_dashboards import sync_dashboards_cmd  # noqa: E402, F401
from ._update import update  # noqa: E402, F401
from ._utils import clear_sessions, verify_model  # noqa: E402, F401
from ._wait import wait  # noqa: E402, F401
