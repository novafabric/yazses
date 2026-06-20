"""Gaze backend Protocol (no third-party import — always importable)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class GazeBackend(Protocol):
    """Estimate gaze direction from the webcam, one sample at a time."""

    @property
    def name(self) -> str: ...

    def estimate(self) -> tuple[float, float] | None:
        """Return ``(yaw, pitch)`` for the current frame, or None if no face/low confidence.

        The camera is opened only while sampling and frames are processed in-RAM —
        never stored or transmitted (ADR-011).
        """
        ...

    def close(self) -> None:
        """Release the camera."""
        ...
