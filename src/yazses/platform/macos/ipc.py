"""macOS IPC — Unix-domain socket transport. Mirrors the Linux backend; the
generic JSON-RPC server/client in :mod:`yazses.ipc` already handles AF_UNIX.
"""

from __future__ import annotations

from pathlib import Path

from yazses.ipc.client import JsonRpcClient
from yazses.ipc.server import JsonRpcServer


def UnixSocketIpcServer(socket_path: Path) -> JsonRpcServer:  # noqa: N802 (factory)
    return JsonRpcServer.unix(socket_path)


def UnixSocketIpcClient(socket_path: Path) -> JsonRpcClient:  # noqa: N802 (factory)
    return JsonRpcClient.unix(socket_path)
