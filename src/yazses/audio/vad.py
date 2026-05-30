import numpy as np

_SILENCE_THRESHOLD = 0.01


def is_silent(audio: np.ndarray, threshold: float = _SILENCE_THRESHOLD) -> bool:
    if audio.size == 0:
        return True
    return float(np.abs(audio).mean()) < threshold
