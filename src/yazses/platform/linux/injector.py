"""Linux injector — wraps the existing inject.auto.get_injector dispatch."""

from __future__ import annotations

import os
import shutil
import subprocess

from yazses.inject.auto import get_injector
from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector


def _xdotool_key_str(combo: str) -> str:
    """Convert 'ctrl+z' → 'ctrl+z', 'shift+Left' → 'shift+Left' for xdotool."""
    return combo.replace("meta", "super")


def _ydotool_key_name(combo: str) -> str:
    """Convert 'ctrl+z' → 'KEY_LEFTCTRL+KEY_Z' for ydotool."""
    _mod_map = {
        "ctrl": "KEY_LEFTCTRL",
        "shift": "KEY_LEFTSHIFT",
        "alt": "KEY_LEFTALT",
        "meta": "KEY_LEFTMETA",
        "super": "KEY_LEFTMETA",
    }
    _key_map = {
        "Return": "KEY_ENTER",
        "Left": "KEY_LEFT",
        "Right": "KEY_RIGHT",
        "Up": "KEY_UP",
        "Down": "KEY_DOWN",
        "BackSpace": "KEY_BACKSPACE",
        "Tab": "KEY_TAB",
        "Escape": "KEY_ESC",
        # Multi-word names whose KEY_<UPPER> fallback would be wrong
        # (KEY_PAGE_UP ≠ KEY_PAGEUP).
        "Page_Up": "KEY_PAGEUP",
        "Page_Down": "KEY_PAGEDOWN",
        "Home": "KEY_HOME",
        "End": "KEY_END",
    }
    parts = combo.split("+")
    result = []
    for p in parts:
        low = p.lower()
        if low in _mod_map:
            result.append(_mod_map[low])
        elif p in _key_map:
            result.append(_key_map[p])
        elif len(p) == 1:
            result.append(f"KEY_{p.upper()}")
        else:
            result.append(f"KEY_{p.upper()}")
    return "+".join(result)


class LinuxInjector:
    """InjectorBackend that auto-selects the best Linux backend at construction.

    Tries the focus-aware backend first (xdotool / ydotool / wtype) and falls
    back to clipboard-paste if that backend fails at runtime.
    """

    def __init__(self) -> None:
        self._primary: BaseInjector = get_injector()
        self._fallback: ClipboardInjector | None
        self._fallback = None if isinstance(self._primary, ClipboardInjector) else ClipboardInjector()
        self._is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))

    def inject(self, text: str) -> None:
        try:
            self._primary.inject(text)
        except Exception:
            if self._fallback is None:
                raise
            self._fallback.inject(text)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        try:
            self._primary.inject_backspaces(count)
        except Exception:
            if self._fallback is None:
                raise
            self._fallback.inject_backspaces(count)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        if self._is_wayland:
            if shutil.which("ydotool"):
                for combo in keys:
                    subprocess.run(
                        ["ydotool", "key", _ydotool_key_name(combo)],
                        check=True,
                        timeout=5,
                    )
                return
            if shutil.which("wtype"):
                for combo in keys:
                    parts = combo.split("+")
                    args: list[str] = ["wtype"]
                    for p in parts[:-1]:
                        args += ["-M", p]
                    args += ["-k", parts[-1]]
                    for p in parts[:-1]:
                        args += ["-m", p]
                    subprocess.run(args, check=True, timeout=5)
                return
        else:
            if shutil.which("xdotool"):
                subprocess.run(
                    ["xdotool", "key", "--clearmodifiers"] + [_xdotool_key_str(k) for k in keys],
                    check=True,
                    timeout=5,
                )
                return
        # Clipboard fallback has no key-sequence capability; silently skip.

    @property
    def backend_name(self) -> str:
        return type(self._primary).__name__
