"""Daemon-level integration for inter-utterance continuation spacing.

Drives the real ``_on_hold_end`` pipeline with fakes to prove that consecutive
hold-to-talk bursts no longer glue together at the boundary — the root cause of
"...words together.Imean,it does not put space between the words."
"""
import time

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _RecordingInjector:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon():
    cfg = Config()
    cfg.filters.disfluency.enabled = False  # keep transcript verbatim
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    # Loud audio so the VAD gate never discards.
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _RecordingInjector()
    d._injector = inj
    return d, inj


def test_first_burst_has_no_leading_space():
    d, inj = _daemon()
    d._engine.text = "hello world"
    d._on_hold_end()
    assert inj.calls == ["hello world"]


def test_second_burst_within_window_gets_leading_space():
    d, inj = _daemon()
    d._engine.text = "hello world"
    d._on_hold_end()
    d._engine.text = "this is me"
    d._on_hold_end()
    assert inj.calls == ["hello world", " this is me"]


def test_closing_punctuation_burst_is_not_spaced():
    # A burst Whisper renders starting with closing punctuation must hug the
    # previous word: "hello world" + ", however" -> "hello world, however".
    # (Leading "." / "…" are stripped earlier by clean_text, so a comma is the
    # realistic case that reaches the spacing step.)
    d, inj = _daemon()
    d._engine.text = "hello world"
    d._on_hold_end()
    d._engine.text = ", however"
    d._on_hold_end()
    assert inj.calls == ["hello world", ", however"]


def test_burst_after_window_starts_fresh():
    d, inj = _daemon()
    d._engine.text = "hello world"
    d._on_hold_end()
    # Pretend the previous injection was long ago, beyond the 30s window.
    d._last_dictation_monotonic = time.monotonic() - 120.0
    d._engine.text = "new thought"
    d._on_hold_end()
    assert inj.calls == ["hello world", "new thought"]


def test_window_zero_disables_continuation_spacing():
    d, inj = _daemon()
    d._config.injection.continuation_window_ms = 0
    d._engine.text = "hello world"
    d._on_hold_end()
    d._engine.text = "this is me"
    d._on_hold_end()
    assert inj.calls == ["hello world", "this is me"]
