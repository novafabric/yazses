import os
import shutil

from yazses.inject.base import BaseInjector
from yazses.inject.clipboard import ClipboardInjector
from yazses.inject.wtype import WtypeInjector
from yazses.inject.xdotool import XdotoolInjector
from yazses.inject.ydotool import YdotoolInjector


def get_injector() -> BaseInjector:
    is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    if is_wayland:
        if shutil.which("ydotool"):
            return YdotoolInjector()
        if shutil.which("wtype"):
            return WtypeInjector()
    else:
        if shutil.which("xdotool"):
            return XdotoolInjector()
    return ClipboardInjector()
