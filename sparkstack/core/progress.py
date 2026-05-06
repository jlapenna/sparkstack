"""Structured progress tracking for the sparkstack orchestrator.

Matches the formatting and logging semantics of sparkrun's LaunchProgress.
"""

from __future__ import annotations

import logging
import time
from enum import IntEnum

from loguru import logger

# Custom log levels to match sparkrun
PROGRESS = 25
VERBOSE = 15

logging.addLevelName(PROGRESS, "PROGRESS")
logging.addLevelName(VERBOSE, "VERBOSE")


class Verbosity(IntEnum):
    """CLI verbosity tiers."""

    DEFAULT = 0  # PROGRESS level (25)
    DETAIL = 1  # INFO level (20)
    VERBOSE = 2  # VERBOSE level (15)
    DEBUG = 3  # DEBUG level (10)


class StackProgress:
    """Structured progress tracker for sparkstack operations.

    All output goes through the `sparkstack.progress` logger.
    """

    def __init__(self, verbosity: Verbosity = Verbosity.DEFAULT) -> None:
        self.verbosity = verbosity
        # Use loguru wrapper or fallback to stdlib logging depending on binding
        # Here we prefer standard logging which loguru can intercept,
        # or we just use loguru directly. spark-stack uses loguru.
        self._log = logger.bind(logger_name="sparkstack.progress")

        self._current_phase: int | None = None
        self._phase_t0: float | None = None
        self._step_total: int = 0
        self._step_current: int = 0
        self._total_phases: int = 0

    def begin_phases(self, total_phases: int) -> None:
        """Set the total number of phases expected."""
        self._total_phases = total_phases

    def phase(self, num: int, label: str) -> None:
        """Start a numbered phase."""
        if self._current_phase is not None:
            self.phase_end()
        self._current_phase = num
        self._phase_t0 = time.monotonic()
        self._step_total = 0
        self._step_current = 0

        # Bind the phase context so all subsequent logs in this phase carry it
        self._log = self._log.bind(phase=num)

        # loguru allows custom levels if registered, but sparkstack didn't
        # explicitly register PROGRESS yet. Let's ensure it's registered
        # using stdlib's level int just in case, or we use loguru.log
        try:
            self._log.log("PROGRESS", "[%d/%d] %s", num, max(self._total_phases, num), label)
        except ValueError:
            # Fallback if loguru level not added yet
            self._log.log(PROGRESS, "[%d/%d] %s", num, max(self._total_phases, num), label)

    def phase_skip(self, num: int, label: str) -> None:
        """Log a phase that is being skipped."""
        if self._current_phase is not None:
            self.phase_end()
        try:
            self._log.log(
                "PROGRESS", "[%d/%d] %s (Skipped)", num, max(self._total_phases, num), label
            )
        except ValueError:
            self._log.log(
                PROGRESS, "[%d/%d] %s (Skipped)", num, max(self._total_phases, num), label
            )

    def phase_end(self, elapsed: float | None = None) -> None:
        """Close the current phase with a done line."""
        if self._phase_t0 is not None:
            dt = elapsed if elapsed is not None else (time.monotonic() - self._phase_t0)
            try:
                self._log.log("PROGRESS", "  done (%.1fs)", dt)
            except ValueError:
                self._log.log(PROGRESS, "  done (%.1fs)", dt)
        self._current_phase = None
        self._phase_t0 = None

        # Unbind phase so logs between phases don't carry the old phase
        self._log = logger.bind(logger_name="sparkstack.progress")

    def begin_steps(self, total: int) -> None:
        """Declare how many sub-steps the phase will report."""
        self._step_total = total
        self._step_current = 0

    def step(self, label: str) -> float:
        """Emit a sub-step line, returning the start timestamp."""
        self._step_current += 1
        if self._step_total > 0:
            msg = f"  Step {self._step_current}/{self._step_total}: {label}"
        else:
            msg = f"  Step {self._step_current}: {label}"

        try:
            self._log.log("PROGRESS", msg)
        except ValueError:
            self._log.log(PROGRESS, msg)

        return time.monotonic()

    def step_done(self, t0: float) -> None:
        """Log elapsed time for the most recent step (info level)."""
        dt = time.monotonic() - t0
        self._log.info("  step done (%.1fs)", dt)
