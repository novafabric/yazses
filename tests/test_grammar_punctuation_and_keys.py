"""Command grammar must tolerate Whisper's punctuation/capitalization, and the
basic-keystroke commands must classify + map to the right ydotool keys.

Whisper transcribes short utterances with a leading capital and a trailing
period ("Undo." not "undo"), which broke the anchored ^...$ command patterns —
so command mode appeared to do nothing.
"""

import sys

import pytest

from yazses.commands.grammar import IntentType, classify
from yazses.inject.ydotool import ydotool_key_args

_linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="ydotool_key_args resolves keycodes via Linux evdev"
)


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


@_linux_only
@pytest.mark.parametrize("combo,names", [
    ("Page_Up", ["KEY_PAGEUP"]),
    ("Page_Down", ["KEY_PAGEDOWN"]),
    ("Home", ["KEY_HOME"]),
    ("End", ["KEY_END"]),
    ("Return", ["KEY_ENTER"]),
    ("ctrl+x", ["KEY_LEFTCTRL", "KEY_X"]),
])
def test_ydotool_key_args_numeric(combo, names):
    # ydotool's `key` ignores symbolic names — args must be numeric
    # <keycode>:<state>, pressed in order then released in reverse.
    from evdev import ecodes
    codes = [getattr(ecodes, n) for n in names]
    expected = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
    assert ydotool_key_args(combo) == expected


@_linux_only
def test_ydotool_ctrl_v_exact_keycodes():
    # Regression guard for the clipboard-paste bug: Ctrl+V must be exactly
    # LEFTCTRL(29) down, V(47) down, V up, LEFTCTRL up.
    assert ydotool_key_args("ctrl+v") == ["29:1", "47:1", "47:0", "29:0"]
