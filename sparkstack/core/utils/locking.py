import contextlib
import fcntl
import os
import sys


class ProcessLock:
    """A file-based lock to prevent concurrent executions."""

    def __init__(self, lockfile: str):
        self.lockfile = lockfile
        self._fd = None

    def __enter__(self):
        # We open the file for writing.
        self._fd = open(self.lockfile, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                f"Error: Another instance is already running (lock held on {self.lockfile}).",
                file=sys.stderr,
            )
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            with contextlib.suppress(OSError):
                os.unlink(self.lockfile)
