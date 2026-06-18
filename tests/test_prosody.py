"""Tests for Prosody Ink (P1 core) — map prosodic marks to text formatting.

The formatter is pure logic and fully tested here; acoustic feature extraction
needs ``parselmouth`` (optional dep) and is exercised only when installed.
Pitch->question is intentionally out of scope (acoustically unreliable).
Spec: design/specs/prosody-ink.md.
"""
from __future__ import annotations

import numpy as np

from yazses.config import ProsodyConfig
from yazses.postprocess.prosody import (
    ProsodyMark,
    ProsodyResult,
    Word,
    annotate,
    format_prosody,
)


def test_emphasis_bolds_word_in_markdown():
    words = ["hello", "world"]
    marks = [ProsodyMark(), ProsodyMark(emphasized=True)]
    assert format_prosody(words, marks) == "hello **world**"


def test_long_pause_inserts_paragraph_break():
    words = ["first", "second"]
    marks = [ProsodyMark(), ProsodyMark(pause_before_s=0.8)]
    assert format_prosody(words, marks, paragraph_pause_s=0.6) == "first\n\nsecond"


def test_short_pause_is_a_plain_space():
    words = ["a", "b"]
    marks = [ProsodyMark(), ProsodyMark(pause_before_s=0.2)]
    assert format_prosody(words, marks, paragraph_pause_s=0.6) == "a b"


def test_style_none_returns_plain_text_even_with_marks():
    words = ["a", "b"]
    marks = [ProsodyMark(emphasized=True), ProsodyMark(pause_before_s=2.0)]
    assert format_prosody(words, marks, style="none") == "a b"


def test_empty_words_returns_empty_string():
    assert format_prosody([], []) == ""


def test_missing_marks_fall_back_to_defaults():
    # Fewer marks than words must not crash; missing -> no emphasis, no break.
    assert format_prosody(["a", "b", "c"], [ProsodyMark(emphasized=True)]) == "**a** b c"


def test_combined_emphasis_and_paragraph():
    words = ["start", "loud", "next"]
    marks = [
        ProsodyMark(),
        ProsodyMark(emphasized=True),
        ProsodyMark(pause_before_s=1.0),
    ]
    assert format_prosody(words, marks, paragraph_pause_s=0.6) == "start **loud**\n\nnext"


# ---- annotate(): the postprocess entry point wired into the daemon ----------
#
# annotate re-renders the FINAL (cleaned, disfluency-filtered) dictation text,
# using Whisper word timings only for spacing/emphasis. Phase 1 ships pause->para
# with no acoustic dep; emphasis needs parselmouth and is mocked at the extractor
# boundary so CI does not require the optional dep. Spec: design/specs/prosody-ink.md.


def _silence(seconds: float, sr: int = 16000) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)


def test_annotate_pause_inserts_paragraph_break_format_none():
    # A >= pause_paragraph_ms inter-word gap becomes a paragraph break even with
    # format="none" (whitespace renders everywhere).
    cfg = ProsodyConfig(enabled=True, format="none", pause_paragraph_ms=700)
    words = [Word("first", 0.0, 0.4), Word("second", 1.3, 1.7)]  # 0.9 s gap
    result = annotate("first second", _silence(1.7), 16000, words, cfg)
    assert isinstance(result, ProsodyResult)
    assert result.text == "first\n\nsecond"
    assert result.paragraph_breaks == 1
    assert result.emphasized == 0


def test_annotate_short_gap_stays_one_line():
    cfg = ProsodyConfig(enabled=True, format="none", pause_paragraph_ms=700)
    words = [Word("a", 0.0, 0.3), Word("b", 0.4, 0.6)]  # 0.1 s gap
    result = annotate("a b", _silence(0.6), 16000, words, cfg)
    assert result.text == "a b"
    assert result.paragraph_breaks == 0


def test_annotate_format_none_never_bolds_even_when_prominent(mocker):
    # Emphasis is suppressed for format="none" regardless of acoustic prominence.
    mocker.patch(
        "yazses.postprocess.prosody._prominence_scores",
        return_value=[1.0, 1.0],
    )
    cfg = ProsodyConfig(enabled=True, format="none", emphasis_enabled=True)
    words = [Word("a", 0.0, 0.3), Word("b", 0.4, 0.6)]
    result = annotate("a b", _silence(0.6), 16000, words, cfg)
    assert "**" not in result.text
    assert result.emphasized == 0


def test_annotate_markdown_bolds_prominent_word(mocker):
    # With format="markdown" and a mocked prominence score above sensitivity,
    # the prominent word is bolded.
    mocker.patch(
        "yazses.postprocess.prosody._prominence_scores",
        return_value=[0.1, 0.9],
    )
    cfg = ProsodyConfig(
        enabled=True, format="markdown", emphasis_enabled=True, emphasis_sensitivity=0.65
    )
    words = [Word("plain", 0.0, 0.3), Word("loud", 0.4, 0.6)]
    result = annotate("plain loud", _silence(0.6), 16000, words, cfg)
    assert result.text == "plain **loud**"
    assert result.emphasized == 1


def test_annotate_emphasis_disabled_drops_bold(mocker):
    mocker.patch(
        "yazses.postprocess.prosody._prominence_scores",
        return_value=[0.9, 0.9],
    )
    cfg = ProsodyConfig(enabled=True, format="markdown", emphasis_enabled=False)
    words = [Word("a", 0.0, 0.3), Word("b", 0.4, 0.6)]
    result = annotate("a b", _silence(0.6), 16000, words, cfg)
    assert "**" not in result.text


def test_annotate_empty_text_returns_empty():
    cfg = ProsodyConfig(enabled=True, format="markdown")
    result = annotate("", _silence(0.1), 16000, [], cfg)
    assert result.text == ""
    assert result.paragraph_breaks == 0
    assert result.emphasized == 0


def test_annotate_reports_latency():
    cfg = ProsodyConfig(enabled=True, format="none")
    words = [Word("a", 0.0, 0.3)]
    result = annotate("a", _silence(0.3), 16000, words, cfg)
    assert result.latency_ms >= 0.0


def test_annotate_more_text_tokens_than_words_does_not_crash():
    # Disfluency/clean can shift token counts; missing word timings degrade to
    # no-break/no-emphasis rather than raising.
    cfg = ProsodyConfig(enabled=True, format="none", pause_paragraph_ms=700)
    words = [Word("a", 0.0, 0.3)]
    result = annotate("a b c", _silence(0.3), 16000, words, cfg)
    assert result.text == "a b c"
