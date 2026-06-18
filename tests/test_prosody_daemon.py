"""Daemon-level integration for Prosody Ink (spec-prosody-ink, Phase 1).

Drives the real ``_on_hold_end`` pipeline with fakes to prove that, when
``[prosody] enabled``, a long inter-word pause in a dictation burst is rendered
as a paragraph break in the injected text — batch + dictation only, off-by-default
behaviour otherwise unchanged.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.postprocess.prosody import Word


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _WordEngine:
    """Engine exposing both transcribe and transcribe_words for the prosody path."""

    def __init__(self, text="", words=None):
        self.text = text
        self.words = words or []
        self.plain_calls = 0
        self.word_calls = 0

    def transcribe(self, *args, **kwargs):
        self.plain_calls += 1
        return self.text

    def transcribe_words(self, *args, **kwargs):
        self.word_calls += 1
        return self.text, self.words


class _RecordingInjector:
    def __init__(self):
        self.calls = []

    def inject(self, text):
        self.calls.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(prosody_enabled, text, words):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0  # isolate prosody from spacing
    cfg.prosody.enabled = prosody_enabled
    cfg.prosody.format = "none"
    cfg.prosody.pause_paragraph_ms = 700
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _WordEngine(text=text, words=words)
    d._padding_buffer = None
    inj = _RecordingInjector()
    d._injector = inj
    return d, inj


def test_long_pause_becomes_paragraph_break_when_enabled():
    words = [Word("first", 0.0, 0.4), Word("second", 1.3, 1.7)]  # 0.9 s gap
    d, inj = _daemon(prosody_enabled=True, text="first second", words=words)
    d._on_hold_end()
    assert inj.calls == ["first\n\nsecond"]
    assert d._engine.word_calls == 1  # used the word-timestamp path


def test_disabled_prosody_uses_plain_transcribe_path():
    words = [Word("first", 0.0, 0.4), Word("second", 1.3, 1.7)]
    d, inj = _daemon(prosody_enabled=False, text="first second", words=words)
    d._on_hold_end()
    assert inj.calls == ["first second"]
    assert d._engine.word_calls == 0
    assert d._engine.plain_calls == 1


def test_prosody_skipped_for_command_intent():
    # A command burst ("select all") dispatches as a key sequence and must never
    # flow through prosody / inject() — even with a long gap in its word timings.
    words = [Word("select", 0.0, 0.4), Word("all", 1.3, 1.7)]  # 0.9 s gap
    d, inj = _daemon(prosody_enabled=True, text="select all", words=words)
    d._config.commands.enabled = True
    keyseqs = []
    inj.inject_key_sequence = lambda keys: keyseqs.append(keys)
    d._on_hold_end()
    assert inj.calls == []          # no dictation injection
    assert keyseqs                  # dispatched as a command instead
