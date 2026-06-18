"""Tests for Punch-In (P1 core) — locate-and-replace-by-respeak candidate logic.

Spec: design/specs/punch-in.md. Pure stdlib (difflib), offline. This covers the
alignment/candidate core; the interactive re-record + confirm UX is P2.
"""
from __future__ import annotations

from yazses.postprocess.punch_in import (
    Candidate,
    apply_top_candidate,
    propose_corrections,
)


def test_locates_best_matching_span_and_proposes_replacement():
    buffer = "the quick brown fox jumps"
    cands = propose_corrections(buffer, "quick brown dog", max_candidates=3)
    assert cands, "expected at least one candidate"
    top = cands[0]
    assert isinstance(top, Candidate)
    assert top.old_text == "quick brown fox"   # closest span to the respoken phrase
    assert top.new_text == "quick brown dog"


def test_candidates_sorted_by_score_descending():
    buffer = "alpha beta gamma delta"
    cands = propose_corrections(buffer, "beta gamma", max_candidates=3)
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)
    assert cands[0].old_text == "beta gamma"
    assert cands[0].score == 1.0   # exact span present


def test_respects_max_candidates_cap():
    buffer = "one two three four five six"
    cands = propose_corrections(buffer, "two three", max_candidates=2)
    assert len(cands) <= 2


def test_filters_below_min_score():
    buffer = "completely unrelated words here"
    cands = propose_corrections(buffer, "xyzzy plugh", min_score=0.5)
    assert cands == []


def test_empty_inputs_return_no_candidates():
    assert propose_corrections("", "anything") == []
    assert propose_corrections("some buffer", "") == []


def test_single_word_respeak_matches_single_word_span():
    buffer = "send the email now"
    cands = propose_corrections(buffer, "females", min_score=0.4)
    # "email" is the nearest single word to the (mis-heard) respoken "females"
    assert cands[0].old_text == "email"


# ---- apply_top_candidate(): build the corrected full burst (P2 apply) -------


def test_apply_top_candidate_replaces_span_in_full_text():
    corrected, cands = apply_top_candidate(
        "the quick brown fox jumps", "quick brown dog"
    )
    assert corrected == "the quick brown dog jumps"
    assert cands and cands[0].new_text == "quick brown dog"


def test_apply_top_candidate_choose_index():
    # Choosing a lower-ranked candidate applies that span instead of the top one.
    last = "alpha beta gamma delta"
    corrected_top, cands = apply_top_candidate(last, "beta gamma", choose=0)
    assert corrected_top == "alpha beta gamma delta"  # top is an exact match -> no change
    # A second candidate (if any) applies its own span.
    if len(cands) > 1:
        corrected_other, _ = apply_top_candidate(last, "beta gamma", choose=1)
        assert corrected_other != corrected_top or cands[1].old_text != cands[0].old_text


def test_apply_top_candidate_no_match_returns_none():
    corrected, cands = apply_top_candidate(
        "completely unrelated words here", "xyzzy plugh", min_score=0.5
    )
    assert corrected is None
    assert cands == []


def test_apply_top_candidate_out_of_range_choice_returns_none():
    corrected, cands = apply_top_candidate("a b c", "b", choose=9)
    assert corrected is None
