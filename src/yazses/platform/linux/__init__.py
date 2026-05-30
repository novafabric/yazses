"""Linux backend bundle. Wraps the existing modules without moving them so the
v1 test suite continues to pass during Phase 0 of the cross-platform refactor.
"""

from __future__ import annotations

from yazses.platform.base import Platform
from yazses.platform.linux.paths import build_paths


def build_platform() -> Platform:
    from yazses.platform.linux.hotkey import LinuxHotkey
    from yazses.platform.linux.injector import LinuxInjector
    from yazses.platform.linux.ipc import UnixSocketIpcClient, UnixSocketIpcServer
    from yazses.platform.linux.lifecycle import LinuxLifecycle
    from yazses.platform.linux.permissions import LinuxPermissions

    paths = build_paths()
    return Platform(
        name="linux",
        default_hotkey="space",
        paths=paths,
        permissions=LinuxPermissions(),
        lifecycle=LinuxLifecycle(paths=paths),
        hotkey_factory=lambda key_id, threshold_ms, on_start, on_end: LinuxHotkey(
            key_id=key_id,
            threshold_ms=threshold_ms,
            on_hold_start=on_start,
            on_hold_end=on_end,
        ),
        injector_factory=LinuxInjector,
        ipc_server_factory=lambda socket_path: UnixSocketIpcServer(socket_path),
        ipc_client_factory=lambda socket_path: UnixSocketIpcClient(socket_path),
        tray_factory=None,  # Linux tray deferred per the cross-platform plan.
        tray_default_enabled=False,
    )


__all__ = ["build_platform"]
