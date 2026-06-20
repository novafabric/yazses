"""Gaze→screen calibration (pure least-squares, no model dependency).

Fits an affine map from gaze angle ``(yaw, pitch)`` to a screen point ``(x, y)``
from a handful of calibration samples (the user looks at known points once). Coarse
by design — it drives look-to-PANE, not look-to-caret.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CalibrationMap:
    """Affine map: [x, y] = A @ [yaw, pitch, 1]. ``A`` is 2x3."""
    A: np.ndarray

    def predict(self, yaw: float, pitch: float) -> tuple[float, float]:
        v = np.array([yaw, pitch, 1.0], dtype="float64")
        x, y = self.A @ v
        return float(x), float(y)


def fit_calibration(
    samples: list[tuple[tuple[float, float], tuple[float, float]]],
) -> CalibrationMap:
    """Least-squares fit of the gaze→screen affine map.

    ``samples`` is ``[((yaw, pitch), (x, y)), ...]``; needs >= 3 non-degenerate
    points (the affine map has 3 coefficients per axis).
    """
    if len(samples) < 3:
        raise ValueError("calibration needs at least 3 points")
    M = np.array([[yaw, pitch, 1.0] for (yaw, pitch), _ in samples], dtype="float64")
    targets = np.array([[x, y] for _, (x, y) in samples], dtype="float64")
    # Solve M @ coeffs = targets for coeffs (3x2); A is its transpose (2x3).
    coeffs, *_ = np.linalg.lstsq(M, targets, rcond=None)
    return CalibrationMap(A=coeffs.T)
