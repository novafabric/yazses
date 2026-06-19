"""Single-instance lock for the daemon (reliability — no duplicate daemons).

Two YazSes daemons running at once (the detached ``yazses start`` path and the
systemd unit) each grab the global hotkey and inject, so every dictation lands
twice. An advisory ``flock`` on a lock file makes a second daemon detect the
first and refuse to start. The lock is held for the process lifetime and the
kernel releases it automatically on exit or crash — so a stale lock never wedges
startup, unlike a bare PID file.

POSIX-only (``fcntl``); on platforms without it the lock degrades to a no-op
(``acquire`` returns True) since the named-pipe IPC there is exclusive anyway.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX (Windows)
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


class SingleInstanceLock:
    """Exclusive, advisory file lock guarding against a second daemon."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = str(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to take the lock. True if held by us, False if another holds it."""
        if self._fd is not None:
            return True  # already held by this instance
        if fcntl is None:  # pragma: no cover - non-POSIX fallback
            return True
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        try:
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
        except OSError:  # pragma: no cover - diagnostic write only
            pass
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock (no-op if not held). The kernel also frees it on exit."""
        if self._fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:  # pragma: no cover
            pass
        finally:
            try:
                os.close(self._fd)
            except OSError:  # pragma: no cover
                pass
            self._fd = None
