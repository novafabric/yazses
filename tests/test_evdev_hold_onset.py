"""Tests for EvdevHoldListener voice-onset behaviour.

Modifier hotkeys (right_alt, right_ctrl, …) must start recording the instant the
key goes down — NOT after the hold threshold, which only fires on a kernel
key-repeat event ~0.5 s later and clips the first words of speech. Character keys
(space) keep the threshold gate + leaked-character cleanup.
"""

from evdev import ecodes

from yazses.hotkeys.evdev_hold import EvdevHoldListener


def _listener(produces_char, threshold_ms=500):
    starts, ends = [], []
    lis = EvdevHoldListener(
        threshold_ms=threshold_ms,
        on_hold_start=lambda leaked: starts.append(leaked),
        on_hold_end=lambda: ends.append(True),
        key_code=ecodes.KEY_RIGHTALT,
        produces_char=produces_char,
    )
    return lis, starts, ends


def test_modifier_starts_on_key_down_without_autorepeat():
    """The whole point: no key-repeat (value==2) event is needed to start."""
    lis, starts, ends = _listener(produces_char=False)
    lis._handle_event(1, t=0.0)          # key down
    assert starts == [0]                  # started immediately, leaked=0
    lis._handle_event(0, t=0.30)          # release after 300 ms
    assert ends == [True]


def test_modifier_ignores_repeat_while_recording():
    lis, starts, ends = _listener(produces_char=False)
    lis._handle_event(1, t=0.0)
    lis._handle_event(2, t=0.25)          # kernel autorepeat — must not re-fire
    lis._handle_event(2, t=0.50)
    assert starts == [0]                  # exactly one start
    lis._handle_event(0, t=0.7)
    assert ends == [True]


def test_modifier_quick_tap_still_brackets_a_recording():
    """A quick tap starts+stops a recording; VAD discards the (silent) audio."""
    lis, starts, ends = _listener(produces_char=False)
    lis._handle_event(1, t=0.0)
    lis._handle_event(0, t=0.04)
    assert starts == [0] and ends == [True]


def test_character_key_waits_for_threshold():
    """Space must NOT start on key-down (it would record before a hold is known);
    it starts once the threshold elapses, reporting leaked characters."""
    lis, starts, ends = _listener(produces_char=True, threshold_ms=500)
    lis._handle_event(1, t=0.0)           # space down — typed one char
    assert starts == []                    # not yet — could be a tap
    lis._handle_event(2, t=0.20)           # before threshold
    assert starts == []
    lis._handle_event(2, t=0.60)           # past threshold → start
    assert starts == [1]                   # one leaked char to clean up
    lis._handle_event(0, t=1.0)
    assert ends == [True]


def test_character_key_tap_below_threshold_never_records():
    lis, starts, ends = _listener(produces_char=True, threshold_ms=500)
    lis._handle_event(1, t=0.0)
    lis._handle_event(0, t=0.10)           # released before threshold = a tap
    assert starts == [] and ends == []
