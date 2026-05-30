"""Envelope follower — turns the raw mic level into a smooth 0..1 intensity.

The daemon reports ``audio_level`` as ``mean(|samples|)`` of the latest audio
chunk (the same metric the VAD uses, see ``system/miclevel.py``). That raw value
is jittery and its absolute scale depends on the mic, so we:

1. Subtract a noise floor derived from the configured ``vad_threshold`` — levels
   at or below the gate map to 0 (no rings while silent).
2. Normalise against an *adaptive* peak that decays slowly, so the brightest
   rings track "loud for *this* speaker" rather than an absolute dB value.
3. Apply asymmetric attack/release smoothing so rings swell quickly on voice
   onset and fade gently, which reads as responsive rather than twitchy.

All state is explicit and ``update`` is pure given its inputs, so the follower is
trivially testable without audio hardware.
"""

from __future__ import annotations

from dataclasses import dataclass

# Smoothing factors per update (0..1): higher = snappier. Attack is faster than
# release so the sonar leaps to voice and lingers as it dies away.
_ATTACK = 0.6
_RELEASE = 0.15
# The adaptive peak never collapses below this, so a whisper after a shout still
# produces visible (not blown-out) rings, and we never divide by ~0.
_MIN_PEAK = 0.02
# Per-update decay of the adaptive peak (multiplicative). Slow enough that a loud
# burst keeps the ceiling high for a second or two at 60 fps.
_PEAK_DECAY = 0.995


@dataclass
class EnvelopeFollower:
    """Stateful smoother. Construct once per overlay session; call :meth:`update`."""

    threshold: float = 0.01
    _value: float = 0.0
    _peak: float = _MIN_PEAK

    def reset(self) -> None:
        """Drop to silence — used when recording stops."""
        self._value = 0.0
        self._peak = _MIN_PEAK

    def update(self, raw_level: float) -> float:
        """Feed one raw ``mean(|samples|)`` reading; return smoothed 0..1 intensity."""
        # Everything at/below the VAD gate is silence.
        above = max(0.0, raw_level - self.threshold)

        # Adaptive ceiling: rise instantly to new peaks, decay slowly otherwise.
        self._peak = max(_MIN_PEAK, self._peak * _PEAK_DECAY, above)
        target = above / self._peak if self._peak > 0 else 0.0
        target = min(1.0, max(0.0, target))

        alpha = _ATTACK if target > self._value else _RELEASE
        self._value += alpha * (target - self._value)
        # Guard tiny negative drift from float error.
        self._value = min(1.0, max(0.0, self._value))
        return self._value

    @property
    def value(self) -> float:
        """The last smoothed intensity, without advancing state."""
        return self._value
