import asyncio
import contextlib
import fcntl
import os
import sys
from pathlib import Path


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


def run_with_lock(lock_name: str, main_coroutine):
    """
    Run an async coroutine with a process lock.
    lock_name: filename of the lock (e.g. '.spark-stack-update-monitoring.lock')
    main_coroutine: the coroutine to run (e.g. main())
    """
    lock_file = Path(__file__).parent.parent.parent.parent / "tmp" / lock_name
    lock_file.parent.mkdir(exist_ok=True)
    with ProcessLock(str(lock_file)):
        asyncio.run(main_coroutine)
