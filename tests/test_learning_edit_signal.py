import time

from yazses.config import Config
from yazses.learning.analysis import analyze, compute_edit_signals
from yazses.learning.store import EventRecord


def _rec(eid, ts, **kw):
    base = dict(
        id=eid, ts=ts, audio_secs=1.0, decode_ms=50.0, model="base.en",
        level=None, sample_rate=16000, intent_type="dictate", intent_action="inject",
        injected=True, discard_reason=None, wrong_flag=False, edit_signal=None,
        retx_distance=None, has_audio=False, raw_text="", cleaned_text="",
        filtered_text="", final_text="", correction_text="", retx_text="",
    )
    base.update(kw)
    return EventRecord(**base)


def test_self_correction_trigger_flags_previous():
    cfg = Config()  # "scratch that" is a default trigger
    t = time.time()
    events = [
        _rec(1, t, raw_text="meet at nine", filtered_text="meet at nine", final_text="meet at nine"),
        _rec(2, t + 3, raw_text="scratch that meet at ten",
             filtered_text="scratch that meet at ten", final_text="scratch that meet at ten"),
    ]
    signals = compute_edit_signals(events, cfg)
    assert signals.get(1) == 1.0
    assert 2 not in signals


def test_redictation_high_overlap_flags_previous():
    cfg = Config()
    t = time.time()
    events = [
        _rec(1, t, raw_text="deploy to cubernetes", filtered_text="deploy to cubernetes",
             final_text="deploy to cubernetes"),
        _rec(2, t + 4, raw_text="deploy to kubernetes", filtered_text="deploy to kubernetes",
             final_text="deploy to kubernetes"),
    ]
    signals = compute_edit_signals(events, cfg)
    assert 1 in signals and 0 < signals[1] <= 1.0


def test_unrelated_utterances_not_flagged():
    cfg = Config()
    t = time.time()
    events = [
        _rec(1, t, filtered_text="write the report", final_text="write the report"),
        _rec(2, t + 5, filtered_text="open the terminal", final_text="open the terminal"),
    ]
    assert compute_edit_signals(events, cfg) == {}


def test_outside_time_window_not_flagged():
    cfg = Config()
    t = time.time()
    events = [
        _rec(1, t, filtered_text="deploy to cubernetes", final_text="deploy to cubernetes"),
        _rec(2, t + 600, filtered_text="deploy to kubernetes", final_text="deploy to kubernetes"),
    ]
    assert compute_edit_signals(events, cfg) == {}


def test_identical_repeat_not_flagged():
    cfg = Config()
    t = time.time()
    events = [
        _rec(1, t, filtered_text="same thing", final_text="same thing"),
        _rec(2, t + 2, filtered_text="same thing", final_text="same thing"),
    ]
    assert compute_edit_signals(events, cfg) == {}


def test_inferred_correction_feeds_vocabulary_proposal():
    # A re-dictation that fixes a mis-transcription should surface a vocabulary
    # proposal WITHOUT any explicit mark-wrong.
    cfg = Config()
    t = time.time()
    events = [
        _rec(1, t, raw_text="use cubernetes", final_text="use cubernetes", filtered_text="use cubernetes"),
        _rec(2, t + 3, raw_text="use kubernetes", final_text="use kubernetes", filtered_text="use kubernetes"),
        _rec(3, t + 20, raw_text="run cubernetes", final_text="run cubernetes", filtered_text="run cubernetes"),
        _rec(4, t + 23, raw_text="run kubernetes", final_text="run kubernetes", filtered_text="run kubernetes"),
    ]
    kinds = {p.kind: p for p in analyze(events, cfg)}
    assert "vocabulary" in kinds
    assert "kubernetes" in kinds["vocabulary"].value
