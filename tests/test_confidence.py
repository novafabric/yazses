"""Tests for Confidence Ink & Voice Re-pick (v2.0.0 Wave A, ADR-v2-001)."""

from yazses.postprocess.confidence import (
    WordConfidence,
    annotate_words,
    low_confidence_spans,
    mark_text,
    repick,
)


def test_annotate_flags_at_or_below_threshold():
    words = [("hello", 0.9), ("wrold", 0.4), ("there", 0.55)]
    out = annotate_words(words, threshold=0.55)
    assert [w.low for w in out] == [False, True, True]  # 0.55 is at threshold → flagged
    assert out[0] == WordConfidence("hello", 0.9, False)


def test_annotate_clamps_out_of_range_probabilities():
    out = annotate_words([("a", 1.7), ("b", -0.3)], threshold=0.5)
    assert out[0].probability == 1.0 and out[0].low is False
    assert out[1].probability == 0.0 and out[1].low is True


def test_low_confidence_spans_groups_contiguous_runs():
    words = [("a", 0.9), ("b", 0.2), ("c", 0.3), ("d", 0.95), ("e", 0.1)]
    assert low_confidence_spans(words, 0.5) == [(1, 3), (4, 5)]


def test_low_confidence_spans_all_high_is_empty():
    words = [("a", 0.9), ("b", 0.8)]
    assert low_confidence_spans(words, 0.5) == []


def test_low_confidence_spans_trailing_run_closed():
    words = [("a", 0.9), ("b", 0.2), ("c", 0.1)]
    assert low_confidence_spans(words, 0.5) == [(1, 3)]


def test_mark_text_wraps_only_low_words():
    words = [("keep", 0.9), ("their", 0.3)]
    assert mark_text(words, 0.5) == "keep ⟨their⟩"


def test_repick_cycles_to_next_alternative():
    alts = ["their", "there", "they're"]
    assert repick(alts, "their") == "there"
    assert repick(alts, "there") == "they're"
    assert repick(alts, "they're") == "their"  # wraps


def test_repick_unknown_current_returns_top():
    assert repick(["there", "their"], "xyz") == "there"


def test_repick_single_or_empty_returns_none():
    assert repick(["only"], "only") is None
    assert repick([], "x") is None


def test_repick_dedupes_before_cycling():
    # duplicates in the beam must not create a no-op "switch to the same word"
    assert repick(["their", "their", "there"], "their") == "there"
