"""Speaker-embedder Protocol (no third-party import — always importable)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from yazses.voiceprint.embedding import Embedding


@runtime_checkable
class SpeakerEmbedder(Protocol):
    """Turn a mono float32 audio buffer into a speaker embedding."""

    @property
    def name(self) -> str: ...

    def embed(self, audio: np.ndarray, sample_rate: int = 16000) -> Embedding:
        """Compute a d-vector for *audio* (≥ a few seconds of one speaker)."""
        ...
