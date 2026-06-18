"""Daemon-level Punch-In re-record + apply (spec-punch-in, P2).

The respeak is recorded and transcribed elsewhere; ``_apply_punch_in`` is the
deterministic orchestration over the ledger + injector that this covers: locate
the closest span in the last burst, delete the old burst, retype the corrected
text, and update the ledger so a later "scratch that" still works. Fakes stand in
for the mic/engine/injector.
"""
from __future__ import annotations

import numpy as np

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio
        self.started = 0

    def start(self):
        self.started += 1

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _RecordingInjector:
    def __init__(self):
        self.backspaces = 0
        self.injected = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        self.backspaces += count

    def inject_key_sequence(self, keys):
        pass


def _daemon():
    cfg = Config()
    cfg.punch_in.enabled = True
    d = Daemon(config=cfg, platform=get_platform())
    inj = _RecordingInjector()
    d._injector = inj
    return d, inj


def test_apply_punch_in_corrects_last_burst():
    d, inj = _daemon()
    d._ledger.record("the quick brown fox")
    result = d._apply_punch_in("brown ox")  # respoken correction of "brown fox"
    assert result["ok"] is True
    assert inj.backspaces == len("the quick brown fox")
    assert inj.injected == ["the quick brown ox"]
    # Ledger now reflects the corrected text for a subsequent "scratch that".
    assert d._ledger.last_text() == "the quick brown ox"


def test_apply_punch_in_no_history_is_safe():
    d, inj = _daemon()
    result = d._apply_punch_in("anything")
    assert result["ok"] is False
    assert inj.backspaces == 0
    assert inj.injected == []


def test_apply_punch_in_no_match_does_not_edit():
    d, inj = _daemon()
    d._ledger.record("the quick brown fox")
    result = d._apply_punch_in("xyzzy plugh")
    assert result["ok"] is False
    assert inj.backspaces == 0
    assert inj.injected == []


def test_apply_punch_in_returns_candidates_for_confirm_ux():
    d, _ = _daemon()
    d._ledger.record("the quick brown fox")
    result = d._apply_punch_in("brown ox")
    assert "candidates" in result
    assert result["candidates"]  # surfaced for the user to confirm/override
    assert result["old"] == "the quick brown fox"
    assert result["new"] == "the quick brown ox"


def test_handle_punch_in_records_respeak_and_applies():
    cfg = Config()
    cfg.punch_in.enabled = True
    cfg.punch_in.record_seconds = 0.0  # no real wait in the test
    d = Daemon(config=cfg, platform=get_platform())
    inj = _RecordingInjector()
    d._injector = inj
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine(text="brown ox")
    d._state.ready = True
    d._ledger.record("the quick brown fox")

    result = d._handle_punch_in(Request(id=1, method="punch_in", params={}))
    assert result["ok"] is True
    assert inj.injected == ["the quick brown ox"]
    assert d._recorder.started == 1


def test_handle_punch_in_disabled_returns_error():
    cfg = Config()
    cfg.punch_in.enabled = False
    d = Daemon(config=cfg, platform=get_platform())
    d._state.ready = True
    result = d._handle_punch_in(Request(id=1, method="punch_in", params={}))
    assert result["ok"] is False
