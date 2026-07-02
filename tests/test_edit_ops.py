"""Tests for Spoken Edit Mode operations + parsing (v2.0.0 Wave A, ADR-v2-003)."""

from yazses.commands.edit_ops import (
    DESTRUCTIVE,
    apply_edit,
    capitalize_last_word,
    delete_last_sentence,
    delete_last_words,
    lowercase_last_word,
    parse_edit,
    replace_words,
    uppercase_last_word,
)


def test_replace_is_case_insensitive_word_boundary():
    r = replace_words("i went their and their car", "their", "there")
    assert r.text == "i went there and there car" and r.changed


def test_replace_does_not_touch_substrings():
    # 'their' inside 'theirs' must survive (word boundary)
    r = replace_words("theirs and their", "their", "there")
    assert r.text == "theirs and there"


def test_replace_missing_old_is_unchanged():
    r = replace_words("hello world", "xyz", "abc")
    assert r.text == "hello world" and r.changed is False


def test_delete_last_sentence_multi():
    r = delete_last_sentence("First one. Second one. Third one.")
    assert r.text == "First one. Second one." and r.changed


def test_delete_last_sentence_single_clears():
    assert delete_last_sentence("Only sentence here").text == ""


def test_delete_last_words_counts():
    assert delete_last_words("one two three four", 2).text == "one two"
    assert delete_last_words("one two", 5).text == ""  # n > len clears
    assert delete_last_words("nothing", 0).changed is False


def test_capitalize_preserves_surrounding_text():
    r = capitalize_last_word("the quick brown fox")
    assert r.text == "the quick brown Fox" and r.changed


def test_upper_and_lower_last_word():
    assert uppercase_last_word("make me loud").text == "make me LOUD"
    assert lowercase_last_word("make me QUIET").text == "make me quiet"


def test_parse_replace_variants():
    assert parse_edit("change their to there") == ("replace", {"old": "their", "new": "there"})
    assert parse_edit("replace foo with bar") == ("replace", {"old": "foo", "new": "bar"})


def test_parse_tolerates_trailing_period():
    # Whisper adds a trailing period on short utterances
    assert parse_edit("delete the last sentence.") == ("delete_sentence", {})


def test_parse_delete_words_number_word_and_digit():
    assert parse_edit("delete the last three words") == ("delete_words", {"n": 3})
    assert parse_edit("delete last 2 words") == ("delete_words", {"n": 2})
    assert parse_edit("delete the last word") == ("delete_words", {"n": 1})


def test_parse_case_ops_and_unknown():
    assert parse_edit("capitalize that") == ("capitalize", {})
    assert parse_edit("uppercase the last word") == ("uppercase", {})
    assert parse_edit("the quick brown fox") is None  # plain dictation, not a command


def test_apply_edit_end_to_end():
    assert apply_edit("i saw their dog", "change their to there").text == "i saw there dog"
    assert apply_edit("hello world", "not a command").changed is False


def test_destructive_set_marks_deletes():
    assert "delete_sentence" in DESTRUCTIVE and "delete_words" in DESTRUCTIVE
    assert "replace" not in DESTRUCTIVE
