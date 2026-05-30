from yazses.overlay.envelope import EnvelopeFollower


def test_silence_stays_zero():
    env = EnvelopeFollower(threshold=0.01)
    for _ in range(10):
        assert env.update(0.0) == 0.0
    assert env.value == 0.0


def test_below_threshold_is_silence():
    env = EnvelopeFollower(threshold=0.05)
    # Level under the VAD gate produces no intensity.
    for _ in range(5):
        assert env.update(0.04) == 0.0


def test_loud_voice_ramps_toward_one():
    env = EnvelopeFollower(threshold=0.01)
    last = 0.0
    for _ in range(20):
        last = env.update(0.5)
    # A sustained loud level normalises against its own peak → near 1.0.
    assert last > 0.9


def test_attack_faster_than_release():
    env = EnvelopeFollower(threshold=0.01)
    # One loud reading lifts the value...
    up = env.update(0.5)
    # ...and a single silent reading does not drop it all the way back (slow release).
    down = env.update(0.0)
    assert up > 0.0
    assert down > 0.0
    assert down < up


def test_reset_returns_to_silence():
    env = EnvelopeFollower(threshold=0.01)
    for _ in range(10):
        env.update(0.5)
    assert env.value > 0.0
    env.reset()
    assert env.value == 0.0


def test_output_always_bounded():
    env = EnvelopeFollower(threshold=0.01)
    for level in [0.0, 1.0, 0.3, 5.0, -1.0, 0.001]:
        out = env.update(level)
        assert 0.0 <= out <= 1.0
