"""
core/updater.py - Abstract base class for service updaters.
"""

from collections.abc import AsyncGenerator

from loguru import logger


class BaseUpdater:
    """Base class for all service updaters yielding progress events."""

    async def run_events(self) -> AsyncGenerator[tuple[str, int]]:
        """
        Main execution loop.
        Yields tuples of (status_message, progress_percentage).
        Must be implemented by subclasses.
        """
        yield ("Starting", 0)
        raise NotImplementedError("Subclasses must implement run_events")

    async def run_cli(self) -> None:
        """Helper to run the updater from a simple CLI script without a UI."""
        try:
            async for msg, pct in self.run_events():
                logger.info(f"[{pct}%] {msg}")
        except Exception as e:
            logger.exception(f"Updater failed: {e}")
            raise
