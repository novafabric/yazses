"""Windows hotkey backend via WH_KEYBOARD_LL low-level keyboard hook.

The hook runs on the thread that calls ``SetWindowsHookExW``; that thread
must pump messages with ``GetMessageW`` for the callback to fire. ``run()``
installs the hook and enters the message loop; ``stop()`` posts ``WM_QUIT``
to the loop, which is thread-safe.

Right Ctrl vs Left Ctrl: the low-level hook reports distinct virtual keys
(VK_RCONTROL vs VK_LCONTROL), so a simple vk-code comparison suffices —
no need to inspect ``LLKHF_EXTENDED``.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

from yazses.hotkeys.hold_detector import HoldDetector

log = logging.getLogger(__name__)


# WinAPI constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

# Virtual key codes (subset; see Microsoft "Virtual-Key Codes" docs).
VK_BACK = 0x08
VK_SPACE = 0x20
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C


_KEY_MAP: dict[str, int] = {
    "space": VK_SPACE,
    "right_ctrl": VK_RCONTROL,
    "left_ctrl": VK_LCONTROL,
    "right_shift": VK_RSHIFT,
    "left_shift": VK_LSHIFT,
    "right_alt": VK_RMENU,
    "left_alt": VK_LMENU,
    "right_meta": VK_RWIN,
    "left_meta": VK_LWIN,
    # macOS naming compatibility.
    "right_option": VK_RMENU,
    "left_option": VK_LMENU,
}

_CHARACTER_KEYS: frozenset[str] = frozenset({"space"})


def resolve_key_id(key_id: str, default: str = "right_ctrl") -> tuple[str, int]:
    """Return (canonical_key_id, vk_code). 'auto' resolves to default."""
    name = key_id.lower()
    if name == "auto":
        name = default
    if name not in _KEY_MAP:
        raise ValueError(
            f"Unknown hotkey {key_id!r}. Supported: {sorted(_KEY_MAP)} or 'auto'."
        )
    return name, _KEY_MAP[name]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


# CALLBACK prototype: LRESULT __stdcall LowLevelKeyboardProc(int, WPARAM, LPARAM)
_LRESULT = ctypes.c_ssize_t
_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    _LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
) if hasattr(ctypes, "WINFUNCTYPE") else None


class WindowsHotkey:
    """HotkeyBackend implementation for Windows."""

    def __init__(
        self,
        key_id: str,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
    ) -> None:
        self._key_id, self._vk = resolve_key_id(key_id)
        self._produces_char = self._key_id in _CHARACTER_KEYS

        self._detector = HoldDetector(threshold_ms=threshold_ms)
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._recording = False

        self._hook_handle: int | None = None
        self._hook_thread_id: int | None = None
        self._hook_proc = None  # Strong ref so the C callback isn't GC'd.
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------

    def run(self) -> None:
        if _LowLevelKeyboardProc is None:
            raise RuntimeError("WINFUNCTYPE unavailable; not running on Windows.")

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._hook_thread_id = kernel32.GetCurrentThreadId()

        # Build and pin the callback.
        self._hook_proc = _LowLevelKeyboardProc(self._on_hook)

        h_module = kernel32.GetModuleHandleW(None)
        self._hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc, h_module, 0
        )
        if not self._hook_handle:
            err = ctypes.get_last_error()
            raise OSError(f"SetWindowsHookExW failed (lastError={err})")

        log.info("WH_KEYBOARD_LL installed for key_id=%s (vk=0x%x)", self._key_id, self._vk)

        try:
            msg = wintypes.MSG()
            while True:
                rv = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if rv == 0:  # WM_QUIT
                    break
                if rv == -1:
                    err = ctypes.get_last_error()
                    raise OSError(f"GetMessageW failed (lastError={err})")
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._teardown()

    def stop(self) -> None:
        self._stop_event.set()
        if self._hook_thread_id is None:
            return
        try:
            user32 = ctypes.windll.user32
            user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
        except Exception:
            log.exception("PostThreadMessageW(WM_QUIT) failed")

    @property
    def key_id(self) -> str:
        return self._key_id

    # ------------------------------------------------------------------

    def _on_hook(self, n_code: int, w_param: int, l_param: int) -> int:
        try:
            if n_code >= 0:
                kbd = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT))[0]
                if int(kbd.vkCode) == self._vk:
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._press()
                    elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                        self._release()
        except Exception:
            log.exception("Hook callback raised")
        # Always pass through; we listen, we never block.
        return ctypes.windll.user32.CallNextHookEx(
            self._hook_handle or 0, n_code, w_param, l_param
        )

    def _press(self) -> None:
        t = time.monotonic()
        self._detector.on_press(t)
        if not self._recording and self._detector.check(t):
            self._recording = True
            leaked = self._detector.leaked_count if self._produces_char else 0
            self._on_hold_start(leaked)

    def _release(self) -> None:
        was_recording = self._recording
        self._recording = False
        self._detector.reset()
        if was_recording:
            self._on_hold_end()

    def _teardown(self) -> None:
        if self._hook_handle is not None:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                log.exception("UnhookWindowsHookEx failed")
            self._hook_handle = None
        self._hook_thread_id = None
        self._hook_proc = None
