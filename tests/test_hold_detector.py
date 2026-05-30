from yazses.hotkeys.hold_detector import HoldDetector


def test_check_false_below_threshold():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    assert d.check(t=0.3) is False


def test_check_true_at_threshold():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    assert d.check(t=0.5) is True


def test_check_fires_only_once():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    assert d.check(t=0.6) is True
    assert d.check(t=0.7) is False   # already fired


def test_leaked_count_counts_key_repeats():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)   # initial press
    d.on_press(t=0.2)   # repeat 1
    d.on_press(t=0.4)   # repeat 2
    assert d.leaked_count == 3


def test_reset_clears_state():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    d.check(t=0.6)
    d.reset()
    assert d.is_pressed is False
    assert d.leaked_count == 0


def test_is_pressed_false_before_press():
    d = HoldDetector(threshold_ms=500)
    assert d.is_pressed is False


def test_is_pressed_true_after_press():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    assert d.is_pressed is True


def test_check_false_when_not_pressed():
    d = HoldDetector(threshold_ms=500)
    assert d.check(t=1.0) is False


def test_detector_reusable_after_reset():
    d = HoldDetector(threshold_ms=500)
    d.on_press(t=0.0)
    d.check(t=0.6)
    d.reset()
    d.on_press(t=1.0)
    assert d.check(t=1.6) is True
