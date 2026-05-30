"""Windows permissions.

Windows doesn't gate WH_KEYBOARD_LL behind a UAC or privacy prompt — it Just
Works. Microphone, on the other hand, has been gated by Settings → Privacy →
Microphone since Windows 10 1903. We probe by asking sounddevice for the
device list; an empty list strongly suggests the user has revoked access (or
no mic is plugged in).
"""

from __future__ import annotations

import logging

from yazses.platform.base import PermissionState

log = logging.getLogger(__name__)


class WindowsPermissions:
    """PermissionsBackend for Windows."""

    def check_keyboard_capture(self) -> PermissionState:
        # WH_KEYBOARD_LL doesn't require a privacy grant. We can't easily
        # verify the hook will install without actually installing it.
        return PermissionState.OK

    def check_microphone(self) -> PermissionState:
        try:
            import sounddevice as sd

            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            return PermissionState.OK if inputs else PermissionState.DENIED
        except Exception as exc:
            log.warning("sounddevice query failed: %s", exc)
            return PermissionState.UNKNOWN

    def request_keyboard_capture(self) -> None:
        # No interactive prompt on Windows.
        return

    def how_to_grant(self) -> str:
        return (
            "If the daemon can't see the microphone, allow it in:\n"
            "  Settings → Privacy & Security → Microphone\n"
            "Or open the pane directly:\n"
            "  start ms-settings:privacy-microphone"
        )
