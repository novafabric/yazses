"""VAD with configurable threshold from accessibility profile."""
from __future__ import annotations

import numpy as np
from yazses.config import AccessibilityConfig


def is_silent_calibrated(audio: np.ndarray, config: AccessibilityConfig) -> bool:
    """RMS-based silence detection using the user-calibrated threshold.

    Drop-in replacement for audio/vad.py:is_silent() that uses
    config.vad_threshold instead of the hardcoded default.
    """
    if audio.size == 0:
        return True
    return bool(np.abs(audio).mean() < config.vad_threshold)
