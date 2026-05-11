import asyncio
import contextlib
import fcntl
import os
import sys
from pathlib import Path


class LockHeldError(RuntimeError):
    """Raised when a process lock is already held by another process."""

    def __init__(self, lockfile: str, holder_pid: int | None = None):
        self.lockfile = lockfile
        self.holder_pid = holder_pid
        if holder_pid:
            msg = (
                f"Another instance is already running "
                f"(lock held on {lockfile} by PID {holder_pid})."
            )
        else:
            msg = f"Another instance is already running (lock held on {lockfile})."
        super().__init__(msg)


class ProcessLock:
    """A file-based lock to prevent concurrent executions.

    On contention, raises ``LockHeldError`` immediately (non-blocking).
    The caller decides how to surface the failure:
    - CLI entry points: catch and ``sys.exit(1)``
    - pytest: catch and ``pytest.exit(msg, returncode=1)``
    """

    def __init__(self, lockfile: str):
        self.lockfile = lockfile
        self._fd = None

    def __enter__(self):
        # Open in 'a+' mode to avoid truncating an existing holder PID
        # before we can read it on contention.
        self._fd = open(self.lockfile, "a+")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder_pid = self._read_holder_pid()
            self._fd.close()
            self._fd = None
            raise LockHeldError(self.lockfile, holder_pid) from None
        # We hold the lock — write our PID so contenders can report it.
        self._fd.seek(0)
        self._fd.truncate(0)
        self._fd.write(str(os.getpid()))
        self._fd.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._fd:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._fd.close()
            with contextlib.suppress(OSError):
                os.unlink(self.lockfile)

    def _read_holder_pid(self) -> int | None:
        """Try to read the PID of the process holding the lock."""
        try:
            assert self._fd is not None  # Called only when fd is open
            self._fd.seek(0)
            content = self._fd.read().strip()
            return int(content) if content else None
        except (OSError, ValueError):
            return None


def run_with_lock(lock_name: str, main_coroutine):
    """
    Run an async coroutine with a process lock.
    lock_name: filename of the lock (e.g. '.sparkstack-update-monitoring.lock')
    main_coroutine: the coroutine to run (e.g. main())
    """
    lock_file = Path(__file__).parent.parent.parent.parent / "tmp" / lock_name
    lock_file.parent.mkdir(exist_ok=True)
    try:
        with ProcessLock(str(lock_file)):
            asyncio.run(main_coroutine)
    except LockHeldError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
