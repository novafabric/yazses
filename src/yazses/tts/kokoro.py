"""Kokoro-82M TTS backend (Apache-2.0) — the default Read-Back voice.

Runs int8 ONNX inference on CPU via ``kokoro-onnx`` (optional ``tts`` extra) and
plays each sentence chunk through ``sounddevice`` (already a core dep for the
recorder). Constructing this backend imports ``kokoro_onnx`` and loads the model;
any failure raises so the factory can fall back to :class:`NullTtsBackend`.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

from yazses.tts.chunking import sentence_chunks

log = logging.getLogger(__name__)


class KokoroTtsBackend:
    """Sentence-chunked Kokoro TTS with barge-in cancel."""

    def __init__(self, config) -> None:
        from kokoro_onnx import Kokoro  # optional `tts` extra; raises if absent

        self._config = config
        self._voice = config.voice if config.voice != "default" else "af_heart"
        self._speed = config.speed
        self._sample_rate = config.sample_rate
        # model_path empty => kokoro-onnx resolves its bundled/cached default.
        self._kokoro = Kokoro(config.model_path) if config.model_path else Kokoro()
        self._cancel = threading.Event()

    @property
    def name(self) -> str:
        return "kokoro"

    def synthesize(self, text: str) -> Iterator[bytes]:
        import numpy as np

        for chunk in sentence_chunks(text):
            if self._cancel.is_set():
                return
            samples, _sr = self._kokoro.create(
                chunk, voice=self._voice, speed=self._speed
            )
            yield np.asarray(samples, dtype="float32").tobytes()

    def speak(self, text: str) -> None:
        import sounddevice as sd

        self._cancel.clear()
        for chunk in sentence_chunks(text):
            if self._cancel.is_set():
                break
            try:
                samples, sr = self._kokoro.create(
                    chunk, voice=self._voice, speed=self._speed
                )
                sd.play(samples, sr)
                sd.wait()
            except Exception as exc:  # never let a playback error break the daemon
                log.debug("Kokoro speak error: %s", exc)
                break

    def cancel(self) -> None:
        self._cancel.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
