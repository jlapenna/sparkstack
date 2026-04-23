"""Bundled binary executables for remote deployment."""

from __future__ import annotations

import hashlib
import platform
from importlib import resources
from pathlib import Path

# Map platform.machine() values to binary suffixes
_ARCH_MAP = {
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "x86_64": "x86_64",
    "AMD64": "x86_64",
}


def _resolve_arch() -> str:
    """Resolve current platform architecture to binary suffix."""
    machine = platform.machine()
    arch = _ARCH_MAP.get(machine)
    if arch is None:
        raise RuntimeError("Unsupported architecture: %s" % machine)
    return arch


def get_binary_path(name: str) -> Path:
    """Return the filesystem path for a platform-appropriate binary.

    Args:
        name: Base binary name (e.g. ``"nv-monitor"``).

    Returns:
        Path to the binary file within the package.

    Raises:
        RuntimeError: If the current architecture is unsupported.
        FileNotFoundError: If the binary is not bundled for this architecture.
    """
    arch = _resolve_arch()
    filename = "%s-%s" % (name, arch)
    path = resources.files(__package__).joinpath(filename)
    # Resolve to actual Path for filesystem operations
    resolved = Path(str(path))
    if not resolved.exists():
        raise FileNotFoundError("Binary not found: %s (looked for %s)" % (name, filename))
    return resolved


def get_binary_resource(name: str):
    """Return a context manager yielding a filesystem Path for a binary.

    Guarantees the path exists on disk even when installed inside a zip.

    Usage::

        with get_binary_resource("nv-monitor") as path:
            subprocess.run(["rsync", str(path), ...])
    """
    arch = _resolve_arch()
    filename = "%s-%s" % (name, arch)
    return resources.as_file(resources.files(__package__).joinpath(filename))


def get_binary_checksum(name: str) -> str:
    """Return SHA-256 hex digest of the bundled binary for the current platform.

    Args:
        name: Base binary name (e.g. ``"nv-monitor"``).

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    with get_binary_resource(name) as path:
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha.update(chunk)
        return sha.hexdigest()
