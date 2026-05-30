from yazses.overlay.animation import SonarModel


def test_no_rings_when_silent():
    m = SonarModel()
    rings = m.tick(now=0.0, intensity=0.0)
    assert rings == []
    assert m.active_count == 0


def test_emits_ring_on_voice():
    m = SonarModel()
    rings = m.tick(now=0.0, intensity=0.8)
    assert len(rings) == 1
    assert m.active_count == 1


def test_ring_expands_and_fades():
    m = SonarModel()
    m.tick(now=0.0, intensity=0.8)
    early = m.tick(now=0.2, intensity=0.0)[0]
    late = m.tick(now=1.0, intensity=0.0)[0]
    # Radius grows, alpha shrinks as the ring ages.
    assert late.radius_frac > early.radius_frac
    assert late.alpha < early.alpha
    assert 0.0 <= late.alpha <= 1.0


def test_ring_expires_after_lifetime():
    m = SonarModel()
    m.tick(now=0.0, intensity=0.8)
    rings = m.tick(now=2.0, intensity=0.0)  # past the ~1.4s lifetime
    assert rings == []
    assert m.active_count == 0


def test_louder_voice_emits_faster():
    loud = SonarModel()
    quiet = SonarModel()
    # Drive both for 1 second of ticks at 50 ms; loud should emit more rings.
    loud_count = 0
    quiet_count = 0
    t = 0.0
    for _ in range(20):
        loud_count += len(_new_emissions(loud, t, 1.0))
        quiet_count += len(_new_emissions(quiet, t, 0.2))
        t += 0.05
    assert loud_count > quiet_count


def _new_emissions(model, now, intensity):
    before = model.active_count
    model.tick(now, intensity)
    after = model.active_count
    return [1] * max(0, after - before)


def test_reset_clears_rings():
    m = SonarModel()
    m.tick(now=0.0, intensity=0.8)
    assert m.active_count == 1
    m.reset()
    assert m.active_count == 0
    assert m.tick(now=0.1, intensity=0.0) == []


def test_intensity_clamped():
    m = SonarModel()
    ring = m.tick(now=0.0, intensity=5.0)[0]
    assert ring.intensity <= 1.0
