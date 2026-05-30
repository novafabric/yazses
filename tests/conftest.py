import numpy as np
import pytest


@pytest.fixture
def sine_audio_3s():
    """3-second 440 Hz sine wave at 16 kHz."""
    sr = 16000
    t = np.linspace(0, 3.0, sr * 3, dtype=np.float32)
    return np.sin(2 * np.pi * 440 * t)


@pytest.fixture
def silent_audio_1s():
    return np.zeros(16000, dtype=np.float32)
