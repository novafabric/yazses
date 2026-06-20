"""Speaker-embedding math (dependency-free core).

The cosine similarity and the per-frame target/non-target decision used by the
Cocktail Filter personal-VAD gate. Pure numpy — no model dependency, so this is
fully unit-testable in CI; the embeddings it compares come from the (optional)
speaker encoder.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Embedding:
    """A speaker embedding (d-vector). Magnitude is irrelevant (cosine compared)."""
    vector: np.ndarray


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [-1, 1]; 0.0 when either vector is all-zero (no NaN)."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def is_target_frame(
    frame_embedding: np.ndarray,
    target: np.ndarray,
    *,
    threshold: float = 0.6,
) -> bool:
    """True if a frame's embedding matches the enrolled target speaker.

    The Cocktail Filter gate keeps frames where this holds and drops the rest, so
    an interfering voice never enters the transcript (design/v2-cognitive-layer
    §3.2). ``threshold`` is ``[cocktail] target_threshold``.
    """
    return cosine_similarity(frame_embedding, target) >= threshold
