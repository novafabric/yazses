"""Tests for the pure per-frame decision (no Qt needed)."""

from yazses.config import OverlayConfig
from yazses.overlay.animation import SonarModel
from yazses.overlay.app import compute_frame
from yazses.overlay.envelope import EnvelopeFollower
from yazses.overlay.poller import StatusSnapshot

SCREEN = (0, 0, 1920, 1080)


def _runtime():
    return EnvelopeFollower(), SonarModel()


def test_idle_with_no_rings_is_hidden():
    env, model = _runtime()
    frame = compute_frame(
        StatusSnapshot(state="idle"),
        OverlayConfig(),
        env,
        model,
        now=0.0,
        cursor=(500, 400),
        screen=SCREEN,
    )
    assert frame.visible is False
    assert frame.top_left is None
    assert frame.ripples == []


def test_recording_voice_emits_and_positions_near_cursor():
    env, model = _runtime()
    frame = compute_frame(
        StatusSnapshot(state="recording", audio_level=0.4, vad_threshold=0.01),
        OverlayConfig(),
        env,
        model,
        now=0.0,
        cursor=(500, 400),
        screen=SCREEN,
    )
    assert frame.visible is True
    assert frame.intensity > 0.0
    assert len(frame.ripples) == 1
    assert frame.top_left == (528, 428)  # cursor + 28 offset


def test_state_only_mode_pulses_without_audio():
    env, model = _runtime()
    cfg = OverlayConfig(react_to_voice=False)
    frame = compute_frame(
        StatusSnapshot(state="recording", audio_level=0.0),
        cfg,
        env,
        model,
        now=0.0,
        cursor=(100, 100),
        screen=SCREEN,
    )
    # Even with zero audio, state-only mode shows a strong steady pulse.
    assert frame.intensity > 0.5
    assert frame.visible is True


def test_fixed_position_used_when_not_cursor():
    env, model = _runtime()
    cfg = OverlayConfig(position="bottom_center")
    frame = compute_frame(
        StatusSnapshot(state="recording", audio_level=0.5),
        cfg,
        env,
        model,
        now=0.0,
        cursor=(0, 0),
        screen=SCREEN,
    )
    assert frame.top_left is not None
    # Centred horizontally regardless of cursor.
    assert frame.top_left[0] == (1920 - cfg.size_px) // 2


def test_rings_keep_showing_briefly_after_release():
    env, model = _runtime()
    cfg = OverlayConfig()
    # Emit a ring while recording...
    compute_frame(
        StatusSnapshot(state="recording", audio_level=0.5),
        cfg, env, model, now=0.0, cursor=(500, 400), screen=SCREEN,
    )
    # ...then stop recording; the ring is still aging, so we stay visible.
    frame = compute_frame(
        StatusSnapshot(state="idle"),
        cfg, env, model, now=0.3, cursor=(500, 400), screen=SCREEN,
    )
    assert frame.visible is True
    assert len(frame.ripples) == 1
