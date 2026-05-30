"""SSH tunnel manager for YazSes remote voice forwarding (cap-001).

Spawns an SSH process with reverse port forwarding:
    ssh -o ExitOnForwardFailure=yes -R 9875:127.0.0.1:9875 [-i key] [-p port] host yazses-agent --listen 9875

The daemon's local injector routes to RemoteInjectorProxy (local_proxy.py) which
sends JSON-RPC inject() calls through this tunnel to the remote yazses-agent.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time

log = logging.getLogger(__name__)

_AGENT_PORT = 9875


class RemoteForwarder:
    """Manages the SSH reverse-tunnel to a remote yazses-agent."""

    def __init__(self, agent_port: int = _AGENT_PORT) -> None:
        self._agent_port = agent_port
        self._process: subprocess.Popen | None = None
        self._connected = False
        self._monitor_thread: threading.Thread | None = None
        self._stopping = False

    def connect(self, host: str, port: int = 22, key_file: str = "") -> None:
        """Establish SSH reverse tunnel to host.

        Raises FileNotFoundError if ssh is not installed.
        Raises RuntimeError if tunnel fails to start.
        """
        if not shutil.which("ssh"):
            raise FileNotFoundError(
                "ssh is not installed or not on PATH. "
                "Install OpenSSH (e.g. 'sudo apt install openssh-client')."
            )
        if self._connected:
            log.warning("RemoteForwarder.connect() called while already connected; reconnecting")
            self.disconnect()

        cmd = ["ssh", "-o", "ExitOnForwardFailure=yes", "-o", "StrictHostKeyChecking=accept-new"]
        if key_file:
            cmd += ["-i", key_file]
        if port != 22:
            cmd += ["-p", str(port)]
        cmd += [
            "-R", f"{self._agent_port}:127.0.0.1:{self._agent_port}",
            host,
            "yazses-agent", "--listen", str(self._agent_port),
        ]

        log.info("RemoteForwarder: spawning %s", " ".join(cmd))
        self._stopping = False
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Give SSH a moment to establish the tunnel
        time.sleep(1.5)
        if self._process.poll() is not None:
            stderr = self._process.stderr.read().decode(errors="replace") if self._process.stderr else ""
            raise RuntimeError(f"SSH tunnel failed to start: {stderr.strip()}")

        self._connected = True
        self._monitor_thread = threading.Thread(target=self._monitor, daemon=True)
        self._monitor_thread.start()
        log.info("RemoteForwarder: connected to %s (pid=%d)", host, self._process.pid)

    def disconnect(self) -> None:
        """Tear down the SSH tunnel."""
        self._stopping = True
        self._connected = False
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        log.info("RemoteForwarder: disconnected")

    def is_connected(self) -> bool:
        return self._connected and (self._process is not None) and (self._process.poll() is None)

    def _monitor(self) -> None:
        """Watch the SSH process; update _connected flag if it exits."""
        while not self._stopping:
            if self._process and self._process.poll() is not None:
                if not self._stopping:
                    log.warning("RemoteForwarder: SSH process exited unexpectedly")
                self._connected = False
                break
            time.sleep(1.0)
