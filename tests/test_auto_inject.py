from unittest.mock import patch
import pytest
from yazses.inject.auto import get_injector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.clipboard import ClipboardInjector


def _which(available: list[str]):
    return lambda cmd: f"/usr/bin/{cmd}" if cmd in available else None


def test_x11_with_xdotool(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["xdotool"])):
        assert isinstance(get_injector(), XdotoolInjector)


def test_wayland_prefers_ydotool_when_daemon_running(monkeypatch):
    # ydotool is only chosen when ydotoold's socket exists (it's useless without).
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wtype"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=True):
        assert isinstance(get_injector(), YdotoolInjector)


def test_wayland_without_ydotoold_falls_back_to_wtype(monkeypatch):
    # ydotool installed but no daemon socket → must NOT pick ydotool (it would
    # fail at runtime); fall back to wtype. This is the GNOME-Wayland fix.
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["ydotool", "wtype"])), \
         patch("yazses.inject.auto.os.path.exists", return_value=False):
        assert isinstance(get_injector(), WtypeInjector)


def test_wayland_falls_back_to_wtype(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    with patch("yazses.inject.auto.shutil.which", side_effect=_which(["wtype"])):
        assert isinstance(get_injector(), WtypeInjector)


def test_no_tools_falls_back_to_clipboard(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with patch("yazses.inject.auto.shutil.which", return_value=None):
        assert isinstance(get_injector(), ClipboardInjector)


def test_x11_no_xdotool_falls_back_to_clipboard(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", ":0")
    with patch("yazses.inject.auto.shutil.which", return_value=None):
        assert isinstance(get_injector(), ClipboardInjector)
