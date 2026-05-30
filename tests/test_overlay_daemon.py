"""Daemon-side wiring for the overlay: status fields + auto-launch gating."""

from yazses.config import Config
from yazses.core.daemon import Daemon, should_launch_overlay
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


def _cfg(enabled: bool) -> Config:
    cfg = Config()
    cfg.overlay.enabled = enabled
    return cfg


def test_should_launch_overlay_disabled():
    assert should_launch_overlay(_cfg(False), {"DISPLAY": ":0"}) is False


def test_should_launch_overlay_enabled_with_x11():
    assert should_launch_overlay(_cfg(True), {"DISPLAY": ":1"}) is True


def test_should_launch_overlay_enabled_with_wayland():
    assert should_launch_overlay(_cfg(True), {"WAYLAND_DISPLAY": "wayland-0"}) is True


def test_should_launch_overlay_enabled_but_headless():
    assert should_launch_overlay(_cfg(True), {}) is False


def test_status_exposes_audio_level_and_threshold():
    cfg = Config()
    cfg.accessibility.vad_threshold = 0.042
    daemon = Daemon(config=cfg, platform=get_platform())
    daemon._state.audio_level = 0.137

    status = daemon._handle_status(Request(method="status"))

    assert status["audio_level"] == 0.137
    assert status["vad_threshold"] == 0.042


def test_status_audio_level_defaults_to_zero():
    daemon = Daemon(config=Config(), platform=get_platform())
    status = daemon._handle_status(Request(method="status"))
    assert status["audio_level"] == 0.0
