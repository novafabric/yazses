"""Windows daemon lifecycle — PID file + detached spawn + HKCU\\Run autostart."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from yazses.platform.base import Paths

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "YazSes"


# Subprocess creation flags — defined here because Linux dev machines don't
# have these constants on the subprocess module.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008
_CREATE_NO_WINDOW = 0x08000000


class WindowsLifecycle:
    """LifecycleBackend for Windows."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        self._paths.pid_file.parent.mkdir(parents=True, exist_ok=True)
        self._paths.pid_file.write_text(str(os.getpid()))

    def clear_pid(self) -> None:
        self._paths.pid_file.unlink(missing_ok=True)

    def read_pid(self) -> int | None:
        try:
            return int(self._paths.pid_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            return None

    def is_running(self) -> bool:
        pid = self.read_pid()
        if pid is None:
            return False
        try:
            # On Windows, os.kill(pid, 0) raises OSError if the process is gone.
            os.kill(pid, 0)
        except OSError:
            return False
        # Best-effort recycle-PID guard via WMIC / tasklist.
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2.0,
                creationflags=_CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        return "yazses" in result.stdout.lower() or "python" in result.stdout.lower()

    # ---- Process spawn / stop ---------------------------------------------

    def start_daemon_detached(self) -> None:
        # CREATE_NEW_PROCESS_GROUP so we can later send CTRL_BREAK_EVENT for a
        # graceful shutdown; DETACHED_PROCESS so the daemon survives the parent.
        flags = _CREATE_NEW_PROCESS_GROUP | _DETACHED_PROCESS | _CREATE_NO_WINDOW
        subprocess.Popen(
            [sys.executable, "-m", "yazses.main"],
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def stop_daemon(self, pid: int) -> None:
        # Try a graceful shutdown first via the IPC `shutdown` RPC. The
        # caller (cli.stop) doesn't know about IPC, so we attempt it here
        # before falling back to TerminateProcess.
        try:
            from yazses.ipc.client import IpcUnreachableError
            from yazses.platform.windows.ipc import NamedPipeIpcClient

            client = NamedPipeIpcClient(self._paths.ipc_socket, timeout_s=1.0)
            try:
                client.call("shutdown")
                return
            except IpcUnreachableError:
                pass
            except Exception as exc:
                log.warning("Graceful shutdown RPC failed: %s; falling back to kill.", exc)
        except Exception:
            log.exception("Could not attempt graceful shutdown")

        # Forceful fallback. signal.SIGTERM on Windows maps to TerminateProcess.
        os.kill(pid, signal.SIGTERM)

    # ---- Autostart (HKCU\Run) ---------------------------------------------

    def install_autostart(self) -> None:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            log.error("winreg unavailable; not on Windows?")
            return
        target = self._tray_executable()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, target)

    def uninstall_autostart(self) -> None:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _RUN_VALUE_NAME)
        except FileNotFoundError:
            pass

    def is_autostart_installed(self) -> bool:
        try:
            import winreg  # type: ignore[import-not-found]
        except ImportError:
            return False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
                return bool(value)
        except (FileNotFoundError, OSError):
            return False

    def _tray_executable(self) -> str:
        # When packaged by PyInstaller, sys.executable points at the bundle
        # binary — that's what we want autostart to launch (in tray mode).
        # When pip-installed, point at the yazses-tray script.
        if getattr(sys, "frozen", False):
            return sys.executable
        candidate = Path(sys.executable).parent / "yazses-tray.exe"
        if candidate.exists():
            return str(candidate)
        # Fallback: launch via the Python interpreter.
        return f'"{sys.executable}" -m yazses.tray.app'
