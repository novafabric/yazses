"""Tests for Ghost Ahead -> endpoint anticipation (P1 core).

Content prediction is a field gap (see card); the shipped pivot anticipates *when*
the speaker stops so the daemon can pre-warm/speculatively finalize and hide
latency. Pure decision logic here; streaming-engine integration is later.
Spec: design/specs/ghost-ahead.md.
"""
from __future__ import annotations

from yazses.stt.endpoint import EndpointAnticipator


def test_fires_when_partial_stable_and_silence_long_enough():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=2)
    assert a.observe("hello world", 0.1) is False   # 1st sighting, short silence
    assert a.observe("hello world", 0.4) is True     # stable 2x + enough silence


def test_does_not_fire_while_partial_still_changing():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=2)
    assert a.observe("hello", 0.5) is False
    assert a.observe("hello world", 0.5) is False     # changed -> count reset
    assert a.observe("hello world", 0.5) is True       # now stable 2x


def test_does_not_fire_when_silence_too_short():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=2)
    a.observe("done", 0.1)
    assert a.observe("done", 0.2) is False             # stable but silence < 0.3


def test_reset_clears_stability_count():
    a = EndpointAnticipator(min_silence_s=0.3, stable_updates=2)
    a.observe("x", 0.5)
    a.reset()
    assert a.observe("x", 0.5) is False                # back to first sighting


def test_blank_partial_never_fires():
    a = EndpointAnticipator(min_silence_s=0.0, stable_updates=1)
    assert a.observe("", 5.0) is False
    assert a.observe("   ", 5.0) is False
