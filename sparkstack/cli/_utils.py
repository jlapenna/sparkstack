"""sparkstack verify-model / clear-sessions — standalone utility commands."""

from __future__ import annotations

import click

from sparkstack.manager.clear_stuck_sessions import clear_stuck_sessions
from sparkstack.manager.verify_hf_model import verify_model as _verify

from . import main


@main.command("verify-model")
@click.argument("repo_id")
@click.pass_context
def verify_model(ctx: click.Context, repo_id: str) -> None:
    """Verify a Hugging Face model repository exists.

    REPO_ID is the HF repo identifier (e.g., 'meta-llama/Llama-3-8B').
    """
    _verify(repo_id)


@main.command("clear-sessions")
@click.pass_context
def clear_sessions(ctx: click.Context) -> None:
    """Reset stuck OpenClaw sessions from 'processing' to 'idle'."""
    clear_stuck_sessions()
