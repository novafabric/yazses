"""Tests for the X11GrabHotkey backend."""
from __future__ import annotations

import threading
import time

import pytest


def _make_hotkey(key_id="space", threshold_ms=300, on_start=None, on_end=None):
    from yazses.platform.linux.hotkey_xgrab import X11GrabHotkey
    return X11GrabHotkey(
        key_id=key_id,
        threshold_ms=threshold_ms,
        on_hold_start=on_start or (lambda leaked: None),
        on_hold_end=on_end or (lambda: None),
    )


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="Unknown hotkey"):
        _make_hotkey(key_id="f13_super_extra")


def test_auto_resolves_to_default():
    hk = _make_hotkey(key_id="auto")
    assert hk.key_id == "right_alt"


def test_known_keys_accepted():
    for key in ["space", "right_ctrl", "left_ctrl", "right_alt", "left_alt",
                "right_meta", "left_meta", "right_shift", "left_shift"]:
        hk = _make_hotkey(key_id=key)
        assert hk.key_id == key


def test_hold_fires_on_start_after_threshold():
    """Timer fires on_hold_start after threshold_ms."""
    started = threading.Event()
    leaked_ref = []

    def on_start(leaked):
        leaked_ref.append(leaked)
        started.set()

    hk = _make_hotkey(key_id="space", threshold_ms=50, on_start=on_start)
    hk._handle_press()
    assert started.wait(timeout=1.0), "on_hold_start never fired"
    assert leaked_ref[0] == 1  # space is a character key, one leaked press


def test_hold_cancelled_on_quick_release():
    """Timer is cancelled when key is released before threshold."""
    started = threading.Event()

    def on_start(leaked):
        started.set()

    hk = _make_hotkey(key_id="space", threshold_ms=500, on_start=on_start)
    hk._handle_press()
    time.sleep(0.05)   # well within 500ms threshold
    hk._handle_release()
    assert not started.wait(timeout=0.6), "on_hold_start should not fire after quick release"


def test_hold_end_fires_after_recording():
    """on_hold_end is called when key released after hold was triggered."""
    ended = threading.Event()
    hk = _make_hotkey(key_id="space", threshold_ms=50, on_end=ended.set)
    hk._handle_press()
    time.sleep(0.1)   # let timer fire
    hk._handle_release()
    assert ended.wait(timeout=0.5), "on_hold_end never fired"


def test_modifier_key_reports_zero_leaked():
    """Modifier keys (not character keys) report 0 leaked presses."""
    leaked_ref = []
    started = threading.Event()

    def on_start(leaked):
        leaked_ref.append(leaked)
        started.set()

    hk = _make_hotkey(key_id="right_ctrl", threshold_ms=50, on_start=on_start)
    hk._handle_press()
    assert started.wait(timeout=1.0)
    assert leaked_ref[0] == 0


def test_stop_cancels_timer():
    """stop() cancels any pending hold timer."""
    started = threading.Event()
    hk = _make_hotkey(key_id="space", threshold_ms=500, on_start=lambda _: started.set())
    hk._handle_press()
    hk.stop()
    assert not started.wait(timeout=0.6), "Timer should be cancelled by stop()"


def test_double_press_ignored():
    """Second _handle_press while key is already held does not start another timer."""
    count = []
    hk = _make_hotkey(key_id="space", threshold_ms=50, on_start=lambda _: count.append(1))
    hk._handle_press()
    hk._handle_press()  # should be ignored
    time.sleep(0.15)
    assert len(count) == 1, "on_hold_start should fire exactly once"
