"""Map a screen point to a coarse zone or to the window under it (pure)."""
from __future__ import annotations


def grid_zone(x: float, y: float, width: int, height: int, rows: int, cols: int) -> int:
    """Row-major zone index 0..rows*cols-1 for a point on a rows×cols grid.

    Out-of-bounds points clamp to the nearest edge cell.
    """
    col = min(cols - 1, max(0, int(x / max(1, width) * cols)))
    row = min(rows - 1, max(0, int(y / max(1, height) * rows)))
    return row * cols + col


def window_at_point(x: float, y: float, windows):
    """Return the id of the first window whose bbox contains (x, y), else None.

    ``windows`` is ``[(id, x, y, w, h), ...]`` (top-level windows, front-to-back).
    """
    for wid, wx, wy, ww, wh in windows:
        if wx <= x < wx + ww and wy <= y < wy + wh:
            return wid
    return None


def resolve_window(calibration, yaw: float, pitch: float, windows):
    """Predict the screen point for a gaze angle and return the window under it.

    Combines the calibration map with :func:`window_at_point` — the end-to-end
    look-to-pane resolution used at hold-start. None if the gaze lands outside all
    windows.
    """
    x, y = calibration.predict(yaw, pitch)
    return window_at_point(x, y, windows)
