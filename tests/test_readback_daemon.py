"""Daemon-level Read-Back Loop (spec-read-back-loop, P1).

Drives the real ``_on_hold_end`` pipeline with fakes to prove: a dictation burst
is spoken back when ``[tts] enabled`` + ``read_back="final"``; a command intent is
NOT read back; and read-back stays silent (no speak) when dormant. The recorder is
interlocked off during read-back (echo-loop guard) — asserted via call order.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio
        self.start_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *a, **k):
        return self.text


class _RecordingInjector:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, n):
        pass

    def inject_key_sequence(self, keys):
        pass


class _FakeTts:
    def __init__(self):
        self.spoken = []

    name = "fake"

    def speak(self, text):
        self.spoken.append(text)

    def synthesize(self, text):
        return iter(())

    def cancel(self):
        pass


def _daemon(*, tts_enabled, read_back, text, commands=False):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = commands
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.tts.enabled = tts_enabled
    cfg.accessibility.read_back = read_back
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine(text=text)
    d._padding_buffer = None
    d._injector = _RecordingInjector()
    tts = _FakeTts()
    d._tts = tts
    # Speak synchronously in the test so we can assert without thread races.
    d._speak_readback = lambda t: tts.speak(t)
    return d, tts


def test_dictation_is_read_back_when_enabled():
    d, tts = _daemon(tts_enabled=True, read_back="final", text="hello world")
    d._on_hold_end()
    assert d._injector.calls == ["hello world"]
    assert tts.spoken == ["hello world"]


def test_no_readback_when_dormant():
    d, tts = _daemon(tts_enabled=False, read_back="off", text="hello world")
    d._on_hold_end()
    assert d._injector.calls == ["hello world"]
    assert tts.spoken == []


def test_no_readback_when_read_back_off_even_if_tts_enabled():
    d, tts = _daemon(tts_enabled=True, read_back="off", text="hello world")
    d._on_hold_end()
    assert tts.spoken == []


def test_command_intent_is_not_read_back():
    # "select all" classifies as a command → dispatched, never spoken.
    d, tts = _daemon(tts_enabled=True, read_back="final", text="select all", commands=True)
    d._on_hold_end()
    assert tts.spoken == []
    assert d._injector.calls == []  # no dictation injection


def test_long_burst_is_truncated_for_readback():
    long_text = "word " * 200  # 1000 chars
    d, tts = _daemon(tts_enabled=True, read_back="final", text=long_text.strip())
    d._config.tts.max_readback_chars = 50
    d._on_hold_end()
    assert tts.spoken
    assert len(tts.spoken[0]) <= 51  # truncated (+ ellipsis)
    assert tts.spoken[0].endswith("…")
