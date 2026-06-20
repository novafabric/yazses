"""Encrypted voiceprint persistence (ADR-012).

The speaker embedding is biometric data, so it is stored only encrypted with the
machine-bound key (reusing ``learning/crypto.py``) and never leaves the machine.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from yazses.voiceprint.embedding import Embedding


def save_voiceprint(embedding: Embedding, path: Path, cipher) -> None:
    """Encrypt and write the embedding vector to *path*."""
    buf = io.BytesIO()
    np.save(buf, np.asarray(embedding.vector, dtype="float32"))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(cipher.encrypt(buf.getvalue()))


def load_voiceprint(path: Path, cipher) -> Embedding | None:
    """Decrypt and load the embedding from *path*, or None if absent/unreadable."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        raw = cipher.decrypt(p.read_bytes())
        vector = np.load(io.BytesIO(raw))
    except Exception:
        return None
    return Embedding(vector=np.asarray(vector, dtype="float32"))
