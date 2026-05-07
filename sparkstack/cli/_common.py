"""Shared CLI infrastructure: logging, async bridge, decorators."""

from __future__ import annotations

import asyncio
import functools
import json
import sys
from pathlib import Path

import click
from loguru import logger

from sparkstack.core.env import PROJECT_ROOT
from sparkstack.core.utils.locking import ProcessLock


def _setup_logging(verbose: int) -> None:
    """Configure loguru based on CLI verbosity level."""
    logger.remove()
    if verbose < 0:  # --quiet
        logger.add(sys.stderr, level="ERROR")
    elif verbose == 0:
        logger.add(sys.stderr, level="WARNING", format="<level>{message}</level>")
    elif verbose == 1:
        logger.add(
            sys.stderr, level="INFO", format="{time:HH:mm:ss} | <level>{level}</level> | {message}"
        )
    else:
        logger.add(sys.stderr, level="DEBUG")


def json_option():
    return click.option(
        "--json",
        "output_json",
        is_flag=True,
        default=False,
        help="Output structured JSON events to stdout (for scripting).",
    )


def setup_command_logging(output_json: bool, verbose: int = 1) -> None:
    """Reconfigure logging for a specific command, enabling JSON output if requested."""
    logger.remove()
    if output_json:

        def _json_sink(message):
            record = message.record
            event = {
                "event_type": "log",
                "level": record["level"].name,
                "message": str(record["message"]),
                "timestamp": record["time"].isoformat(),
            }
            if "service" in record["extra"]:
                event["service"] = record["extra"]["service"]
            if "phase" in record["extra"]:
                event["phase"] = record["extra"]["phase"]

            sys.stdout.write(json.dumps(event) + "\n")
            sys.stdout.flush()

        logger.add(_json_sink, level="INFO", format="{message}")
    else:
        _setup_logging(verbose)


def run_async(coro) -> None:
    """Bridge a sync Click command to an async coroutine."""
    asyncio.run(coro)


def with_process_lock(lock_name: str):
    """Decorator that wraps a Click command function with a ProcessLock."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            lock_file = Path("tmp") / f".sparkstack-{lock_name}.lock"
            lock_file.parent.mkdir(exist_ok=True)
            with ProcessLock(str(lock_file)):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def resolve_stack_dir(name: str | None = None) -> Path:
    """Resolve a stack name to its absolute directory path.

    Args:
        name: Stack name or "current". If None, resolves to "current".

    Returns:
        Resolved absolute path to the stack directory.
    """
    if name and name != "current":
        return (PROJECT_ROOT / "sparkstack-registry" / "stacks" / name).resolve()
    return (PROJECT_ROOT / "current").resolve()
