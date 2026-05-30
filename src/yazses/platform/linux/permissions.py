"""Linux permissions — evdev access (input group) and microphone availability."""

from __future__ import annotations

import os
from pathlib import Path

from yazses.platform.base import PermissionState


class LinuxPermissions:
    """PermissionsBackend implementation for Linux."""

    def check_keyboard_capture(self) -> PermissionState:
        input_devs = list(Path("/dev/input").glob("event*"))
        if not input_devs:
            return PermissionState.UNKNOWN
        if any(os.access(str(d), os.R_OK) for d in input_devs):
            return PermissionState.OK
        return PermissionState.DENIED

    def check_microphone(self) -> PermissionState:
        # Linux has no per-app microphone gating; if PortAudio sees a device,
        # the daemon can use it.
        try:
            import sounddevice as sd

            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            return PermissionState.OK if inputs else PermissionState.UNKNOWN
        except Exception:
            return PermissionState.UNKNOWN

    def request_keyboard_capture(self) -> None:
        # No interactive prompt on Linux — the user must add themselves to the
        # input group manually, then re-login.
        return

    def how_to_grant(self) -> str:
        return (
            "Add yourself to the input group and re-login:\n"
            "    sudo usermod -aG input $USER\n"
            "Then log out and back in (or reboot) for the change to take effect."
        )
