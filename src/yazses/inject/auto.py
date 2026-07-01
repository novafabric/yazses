import os
import shutil

from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector


def ydotool_socket_path() -> str:
    """The socket path ydotool's client uses (env override, else the default)."""
    sock = os.environ.get("YDOTOOL_SOCKET")
    if sock:
        return sock
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, ".ydotool_socket")


def ydotool_ready() -> bool:
    """True only when ydotool is installed AND ydotoold's socket is present.

    ydotool is useless without a running ydotoold (it fails with
    "failed to connect socket ... ydotool_socket"). Gating selection on the
    socket means we only pick ydotool when it will actually work, and otherwise
    fall through to wtype/clipboard.
    """
    return bool(shutil.which("ydotool")) and os.path.exists(ydotool_socket_path())


def wl_copy_ready() -> bool:
    """True when wl-copy is installed — required for clipboard-paste injection
    on Wayland."""
    return bool(shutil.which("wl-copy"))


def _is_gnome_or_kde() -> bool:
    """GNOME and KDE block wtype and force ydotool for injection. ydotool's
    ``type`` command drops the final key-up event on those compositors, so the
    kernel treats the last key as held and auto-repeats it (a flood of
    ``mmmm…``). Detect them so we can paste via the clipboard instead, which
    sends no per-character keystrokes and therefore cannot stick."""
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    return any(marker in desktop for marker in ("gnome", "kde", "plasma"))


def get_injector() -> BaseInjector:
    is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if is_wayland:
        # GNOME/KDE: `ydotool type` drops the final key-up and the kernel
        # auto-repeats the last character. Clipboard-paste (wl-copy + one
        # Ctrl+V) sends no per-character keystrokes, so it can't stick — prefer
        # it whenever a paste path (ydotoold) and wl-copy are both available.
        if _is_gnome_or_kde() and ydotool_ready() and wl_copy_ready():
            return ClipboardInjector()
        # Other Wayland compositors: ydotool when its daemon is up, else wtype
        # (wlroots-only); neither exhibits the GNOME/KDE stuck-key flood.
        if ydotool_ready():
            return YdotoolInjector()
        if shutil.which("wtype"):
            return WtypeInjector()
    else:
        if shutil.which("xdotool"):
            return XdotoolInjector()
    return ClipboardInjector()
