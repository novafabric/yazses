"""macOS permission checks — Accessibility (TCC) and Microphone (AVCaptureDevice).

Both require PyObjC. Imports are local so that the module can be imported on
non-Mac systems for static checks without crashing.
"""

from __future__ import annotations

import logging

from yazses.platform.base import PermissionState

log = logging.getLogger(__name__)


# AVAuthorizationStatus values from Apple's AVFoundation framework.
_AV_NOT_DETERMINED = 0
_AV_RESTRICTED = 1
_AV_DENIED = 2
_AV_AUTHORIZED = 3


class MacosPermissions:
    """PermissionsBackend for macOS."""

    def check_keyboard_capture(self) -> PermissionState:
        try:
            from ApplicationServices import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (  # type: ignore[import-not-found]
                kCFBooleanFalse,
            )
        except ImportError:
            log.warning("PyObjC ApplicationServices not available")
            return PermissionState.UNKNOWN

        # Pass prompt=False to check silently. The hotkey backend triggers the
        # prompt explicitly via :meth:`request_keyboard_capture` when needed.
        options = {kAXTrustedCheckOptionPrompt: kCFBooleanFalse}
        return PermissionState.OK if AXIsProcessTrustedWithOptions(options) else PermissionState.DENIED

    def check_microphone(self) -> PermissionState:
        try:
            from AVFoundation import (  # type: ignore[import-not-found]
                AVCaptureDevice,
                AVMediaTypeAudio,
            )
        except ImportError:
            log.warning("PyObjC AVFoundation not available")
            return PermissionState.UNKNOWN

        status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
        if status == _AV_AUTHORIZED:
            return PermissionState.OK
        if status == _AV_DENIED or status == _AV_RESTRICTED:
            return PermissionState.DENIED
        return PermissionState.UNKNOWN  # NotDetermined → user hasn't been asked yet

    def request_keyboard_capture(self) -> None:
        try:
            from ApplicationServices import (  # type: ignore[import-not-found]
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (  # type: ignore[import-not-found]
                kCFBooleanTrue,
            )
        except ImportError:
            return
        AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: kCFBooleanTrue})

    def how_to_grant(self) -> str:
        return (
            "Grant Accessibility access in System Settings:\n"
            "  System Settings → Privacy & Security → Accessibility → enable YazSes.\n"
            "Or open the pane directly:\n"
            "  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility'"
        )
