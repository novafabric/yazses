"""Sonar ripple model — the pure animation state behind the overlay.

A :class:`SonarModel` is fed ``(now, intensity)`` on every render tick. It emits
new rings on a cadence that gets faster and brighter with louder voice, and ages
existing rings outward until they fade. The Qt widget just paints whatever
:meth:`tick` returns; all timing/geometry lives here so it is testable with an
injected clock and no display.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A ring travels from radius 0 to ``max_radius_frac`` of the half-window over
# ``_LIFETIME_S`` seconds, fading its alpha to 0 as it goes.
_LIFETIME_S = 1.4
# Fastest / slowest gap between emitted rings (seconds). Louder voice -> shorter.
_MIN_EMIT_GAP_S = 0.12
_MAX_EMIT_GAP_S = 0.6
# Below this intensity we stop emitting new rings (existing ones still age out).
_EMIT_FLOOR = 0.04


@dataclass(frozen=True)
class Ripple:
    """A single expanding ring, as the widget needs to draw it."""

    radius_frac: float  # 0..1 fraction of the half-window radius
    alpha: float        # 0..1 opacity
    intensity: float    # voice intensity captured at birth (drives stroke width/glow)


@dataclass
class SonarModel:
    """Emits and ages sonar rings. Stateful; one per overlay session."""

    _births: list[tuple[float, float]] = field(default_factory=list)  # (born_at, intensity)
    _last_emit: float = -1.0e9
    _next_gap: float = _MIN_EMIT_GAP_S

    def reset(self) -> None:
        self._births.clear()
        self._last_emit = -1.0e9

    def tick(self, now: float, intensity: float) -> list[Ripple]:
        """Advance to ``now`` with the current voice ``intensity``; return live rings."""
        intensity = min(1.0, max(0.0, intensity))

        # Emit a new ring when enough time has passed and there's voice present.
        if intensity > _EMIT_FLOOR and (now - self._last_emit) >= self._next_gap:
            self._births.append((now, intensity))
            self._last_emit = now
            # Louder -> shorter gap to the next ring.
            self._next_gap = _MAX_EMIT_GAP_S - (_MAX_EMIT_GAP_S - _MIN_EMIT_GAP_S) * intensity

        # Age rings; drop any past their lifetime.
        live: list[Ripple] = []
        survivors: list[tuple[float, float]] = []
        for born_at, born_intensity in self._births:
            age = now - born_at
            if age < 0 or age >= _LIFETIME_S:
                if age < 0:
                    survivors.append((born_at, born_intensity))  # clock skew guard
                continue
            progress = age / _LIFETIME_S
            live.append(
                Ripple(
                    radius_frac=progress,
                    alpha=1.0 - progress,
                    intensity=born_intensity,
                )
            )
            survivors.append((born_at, born_intensity))
        self._births = survivors
        return live

    @property
    def active_count(self) -> int:
        return len(self._births)
