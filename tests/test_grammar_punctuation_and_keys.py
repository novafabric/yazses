"""Command grammar must tolerate Whisper's punctuation/capitalization, and the
basic-keystroke commands must classify + map to the right ydotool keys.

Whisper transcribes short utterances with a leading capital and a trailing
period ("Undo." not "undo"), which broke the anchored ^...$ command patterns —
so command mode appeared to do nothing.
"""

import pytest

from yazses.commands.grammar import IntentType, classify
from yazses.platform.linux.injector import _ydotool_key_name


@pytest.mark.parametrize("text,action", [
    ("Undo.", "undo"),
    ("undo", "undo"),
    ("  Save file.  ", "save"),
    ("Select all.", "select_all"),
    ("Copy that.", "copy"),
    ("Paste!", "paste"),
    ("Comment this.", "comment"),
    ("Delete the last three words.", "delete_words"),
    ("Go to line 42.", "go_to_line"),
    ("Run the tests.", "run_tests"),
])
def test_commands_survive_whisper_punctuation(text, action):
    intent = classify(text)
    assert intent.intent != IntentType.DICTATE, f"{text!r} fell through to dictation"
    assert intent.action == action


def test_numbers_still_normalised_with_trailing_period():
    intent = classify("Delete the last three words.")
    assert intent.action == "delete_words"
    assert intent.args == {"n": "3"}


@pytest.mark.parametrize("text,action", [
    ("New line.", "press_enter"),
    ("Press enter.", "press_enter"),
    ("Enter.", "press_enter"),
    ("Tab.", "press_tab"),
    ("Escape.", "press_escape"),
    ("Press backspace.", "press_backspace"),
    ("Cut.", "cut"),
    ("Page up.", "page_up"),
    ("Page down.", "page_down"),
    ("Go up.", "arrow_up"),
    ("Move down.", "arrow_down"),
    ("Go left.", "arrow_left"),
    ("Go right.", "arrow_right"),
    ("End of line.", "line_end"),
    ("Go to beginning of the line.", "line_home"),
])
def test_basic_keystroke_commands(text, action):
    intent = classify(text)
    assert intent.intent != IntentType.DICTATE, f"{text!r} fell through to dictation"
    assert intent.action == action


def test_interior_punctuation_preserved_in_args():
    # Only outer punctuation is stripped; a filename's dot must survive.
    intent = classify("Open file main.py.")
    assert intent.action == "go_to_file"
    assert intent.args.get("name") == "main.py"


def test_plain_dictation_still_dictation():
    intent = classify("the quick brown fox jumped over the lazy dog.")
    assert intent.intent == IntentType.DICTATE


@pytest.mark.parametrize("combo,expected", [
    ("Page_Up", "KEY_PAGEUP"),
    ("Page_Down", "KEY_PAGEDOWN"),
    ("Home", "KEY_HOME"),
    ("End", "KEY_END"),
    ("Return", "KEY_ENTER"),
    ("ctrl+x", "KEY_LEFTCTRL+KEY_X"),
])
def test_ydotool_key_mapping(combo, expected):
    assert _ydotool_key_name(combo) == expected
