"""Tests for inter-utterance continuation spacing (root-cause fix for burst gluing).

The daemon injects each hold-to-talk burst independently. Without a separator,
the last word of one burst glues to the first word of the next:
"words together" + "I mean" -> "words togetherI mean". These tests pin the
smart-leading-space policy: prepend a space when continuing a recent dictation,
but suppress it before closing punctuation.
"""
from yazses.postprocess.spacing import continuation_prefix


def test_no_prefix_when_no_recent_injection():
    # First burst of a session — never prepend a space.
    assert continuation_prefix("hello world", had_recent_injection=False) == ""


def test_prepends_space_when_continuing():
    assert continuation_prefix("this is me", had_recent_injection=True) == " "


def test_suppresses_space_before_closing_punctuation():
    for punct in [".", ",", "!", "?", ";", ":", ")"]:
        assert continuation_prefix(punct + " done", had_recent_injection=True) == "", punct


def test_empty_text_gets_no_prefix():
    assert continuation_prefix("", had_recent_injection=True) == ""


def test_space_before_opening_quote_or_paren_is_kept():
    # A new clause that starts with an opening delimiter still wants a leading space.
    assert continuation_prefix('"quoted"', had_recent_injection=True) == " "
    assert continuation_prefix("(aside)", had_recent_injection=True) == " "
