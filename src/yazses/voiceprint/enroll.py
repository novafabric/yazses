"""Speaker enrollment — turn a recording into a stored voiceprint.

Records a short sample, computes the speaker embedding, and saves it encrypted
(ADR-012). Used by ``yazses enroll-voice`` and reused by Cocktail Filter /
Voiceprint Mind. The recorder + embedder are injected so the flow is testable
without a microphone or model.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from yazses.voiceprint.embedding import Embedding


def enroll(
    record_fn: Callable[[float, int], np.ndarray],
    embedder,
    *,
    seconds: float = 25.0,
    sample_rate: int = 16000,
) -> Embedding:
    """Record ``seconds`` of speech and return its speaker embedding.

    ``record_fn(seconds, sample_rate) -> audio`` captures the sample; ``embedder``
    is a :class:`SpeakerEmbedder`. Raises ``ValueError`` if nothing is captured.
    """
    audio = record_fn(seconds, sample_rate)
    if audio is None or np.asarray(audio).size == 0:
        raise ValueError("no audio captured during enrollment")
    return embedder.embed(audio, sample_rate)
