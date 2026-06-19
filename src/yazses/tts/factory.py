"""TTS backend factory (spec-read-back-loop).

``build_tts`` honours the dormancy contract used across YazSes (parallel to
``learning.build_writer`` / ``build_cleaner``):

- ``[tts] enabled = false`` -> ``None`` (fully dormant; nothing imported/downloaded).
- enabled but the engine import / model is unavailable -> :class:`NullTtsBackend`
  (degrade, never crash).
"""
from __future__ import annotations

import logging

from yazses.tts.base import TtsBackend
from yazses.tts.null import NullTtsBackend

log = logging.getLogger(__name__)


def build_tts(config) -> TtsBackend | None:
    """Return a TTS backend for *config*, or None when ``[tts]`` is disabled."""
    if not getattr(config, "enabled", False):
        return None

    engine = getattr(config, "engine", "kokoro")
    try:
        if engine == "kokoro":
            from yazses.tts.kokoro import KokoroTtsBackend

            return KokoroTtsBackend(config)
        # melo / kitten not yet implemented — degrade to a silent backend rather
        # than crash, so enabling them is harmless until they ship.
        log.warning("TTS engine %r not available; read-back will be silent.", engine)
        return NullTtsBackend()
    except Exception as exc:
        log.warning(
            "TTS engine %r unavailable (%s); install the `tts` extra "
            "(uv sync --extra tts). Read-back will be silent.",
            engine, exc,
        )
        return NullTtsBackend()
