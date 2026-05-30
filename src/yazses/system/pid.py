import os
from pathlib import Path

_PID_FILE = Path.home() / ".local" / "share" / "yazses" / "daemon.pid"


def write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def read_pid() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        return int(_PID_FILE.read_text().strip())
    except ValueError:
        return None


def clear_pid() -> None:
    _PID_FILE.unlink(missing_ok=True)


def is_running() -> bool:
    pid = read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — assume it's running.
        return True
    # Guard against recycled PIDs: verify the process is actually our daemon.
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
        return "yazses" in cmdline
    except OSError:
        return True
