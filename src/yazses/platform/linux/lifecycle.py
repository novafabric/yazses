"""Linux daemon lifecycle — PID file + detached-spawn + systemd autostart."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from yazses.platform.base import Paths
from yazses.system import pid as pid_module


class LinuxLifecycle:
    """LifecycleBackend implementation for Linux."""

    def __init__(self, paths: Paths) -> None:
        self._paths = paths

    # ---- PID file ----------------------------------------------------------

    def write_pid(self) -> None:
        pid_module.write_pid()

    def clear_pid(self) -> None:
        pid_module.clear_pid()

    def read_pid(self) -> int | None:
        return pid_module.read_pid()

    def is_running(self) -> bool:
        return pid_module.is_running()

    # ---- Process spawn / stop ---------------------------------------------

    def start_daemon_detached(self) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "yazses.main"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_daemon(self, pid: int) -> None:
        os.kill(pid, signal.SIGTERM)

    # ---- Autostart (systemd --user) ---------------------------------------

    @property
    def _service_file(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / "yazses.service"

    def install_autostart(self) -> None:
        # The full installer lives in install.sh. This method is a thin entry
        # point for "yazses install-service" workflows; it just enables the
        # unit if it's already been written by install.sh.
        if not self._service_file.exists():
            raise FileNotFoundError(
                f"systemd unit not found at {self._service_file}. "
                "Run install.sh first."
            )
        if not shutil.which("systemctl"):
            raise RuntimeError("systemctl not found; cannot manage autostart.")
        subprocess.run(["systemctl", "--user", "enable", "--now", "yazses.service"], check=True)

    def uninstall_autostart(self) -> None:
        if not shutil.which("systemctl"):
            return
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", "yazses.service"],
            check=False,
        )

    def is_autostart_installed(self) -> bool:
        if not shutil.which("systemctl"):
            return False
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", "yazses.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and "enabled" in result.stdout
