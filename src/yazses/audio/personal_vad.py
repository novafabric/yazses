"""Cocktail Filter P1 — personal-VAD gate (design/v2-cognitive-layer §3.2).

Keep only audio frames that match the enrolled target speaker, dropping frames
dominated by another voice so the interferer's words never reach STT. The per-frame
speaker embedder is injected (the real one is the optional ``voiceprint`` extra);
the gate decision reuses ``voiceprint.embedding.is_target_frame``. Pure numpy.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from yazses.voiceprint.embedding import is_target_frame


def gate(
    audio: np.ndarray,
    target: np.ndarray,
    embed_frame: Callable[[np.ndarray], np.ndarray],
    *,
    sample_rate: int = 16000,
    window_ms: int = 500,
    threshold: float = 0.5,
) -> np.ndarray:
    """Return *audio* with non-target-speaker windows removed.

    The buffer is scored in ``window_ms`` windows (a speaker embedder needs ~0.5s+
    of audio to identify a speaker). ``embed_frame(window) -> vector`` produces a
    speaker embedding; a window is kept when it matches ``target`` at/above
    ``threshold``. Returns an empty array when nothing matches (the daemon then
    treats it as the existing "silent" discard).
    """
    if audio.size == 0:
        return np.array([], dtype=audio.dtype if audio.dtype else "float32")
    win_len = max(1, int(sample_rate * window_ms / 1000))
    kept: list[np.ndarray] = []
    for start in range(0, audio.size, win_len):
        window = audio[start:start + win_len]
        if window.size == 0:
            continue
        emb = embed_frame(window)
        if is_target_frame(emb, target, threshold=threshold):
            kept.append(window)
    if not kept:
        return np.array([], dtype=audio.dtype)
    return np.concatenate(kept)
