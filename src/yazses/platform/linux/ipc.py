"""Linux IPC — Unix-domain socket transport for the JSON-RPC server/client.

The actual JSON-RPC framing lives in yazses.ipc.{server,client}; this module
just instantiates them with AF_UNIX. macOS reuses the same transport.
"""

from __future__ import annotations

from pathlib import Path

from yazses.ipc.client import JsonRpcClient
from yazses.ipc.server import JsonRpcServer


def UnixSocketIpcServer(socket_path: Path) -> JsonRpcServer:  # noqa: N802 (factory)
    return JsonRpcServer.unix(socket_path)


def UnixSocketIpcClient(socket_path: Path) -> JsonRpcClient:  # noqa: N802 (factory)
    return JsonRpcClient.unix(socket_path)
