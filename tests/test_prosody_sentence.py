"""Tests for pause→sentence punctuation (v2.0.0 Wave A, ADR-v2-002).

Guards that the new ``sentence_pause_s`` is opt-in: with it at 0 (default) the
formatter behaves exactly as before (no periods inserted).
"""

from yazses.postprocess.prosody import ProsodyMark, format_prosody


def _marks(gaps):
    return [ProsodyMark(pause_before_s=g) for g in gaps]


def test_sentence_pause_inserts_period():
    words = ["hello", "world", "next", "one"]
    # gap before "next" is a sentence pause (>=0.4, <0.7 paragraph)
    marks = _marks([0.0, 0.1, 0.5, 0.1])
    out = format_prosody(words, marks, paragraph_pause_s=0.7, sentence_pause_s=0.4)
    assert out == "hello world. next one"


def test_paragraph_pause_also_closes_sentence_when_enabled():
    words = ["end", "here", "new", "para"]
    marks = _marks([0.0, 0.1, 0.9, 0.1])  # 0.9 >= paragraph threshold
    out = format_prosody(words, marks, paragraph_pause_s=0.7, sentence_pause_s=0.4)
    assert out == "end here.\n\nnew para"


def test_disabled_by_default_inserts_no_periods():
    words = ["hello", "world", "next"]
    marks = _marks([0.0, 0.1, 0.5])
    # sentence_pause_s defaults to 0.0 → unchanged behaviour (no period)
    out = format_prosody(words, marks, paragraph_pause_s=0.7)
    assert out == "hello world next"


def test_no_double_period_when_already_punctuated():
    words = ["done.", "next", "word"]
    marks = _marks([0.0, 0.5, 0.1])
    out = format_prosody(words, marks, paragraph_pause_s=0.7, sentence_pause_s=0.4)
    assert out == "done. next word"  # 'done.' already ends a sentence
