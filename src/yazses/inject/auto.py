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


def get_injector() -> BaseInjector:
    is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if is_wayland:
        # Prefer ydotool when its daemon is up (works on every compositor,
        # including GNOME/KDE where wtype is blocked); else wtype (wlroots only).
        if ydotool_ready():
            return YdotoolInjector()
        if shutil.which("wtype"):
            return WtypeInjector()
    else:
        if shutil.which("xdotool"):
            return XdotoolInjector()
    return ClipboardInjector()
