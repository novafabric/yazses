"""Streaming STT engine using LocalAgreement 2-iteration policy (ADR-002).

Wraps WhisperModel to decode rolling audio windows and emit only stable
prefix deltas — text that has been confirmed by at least 2 consecutive
decode passes.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class PartialHypothesis:
    """Emitted by StreamingEngine for each stable prefix delta."""

    text: str          # the NEW characters since last emission (delta only)
    is_stable: bool    # True = LocalAgreement confirmed; False = tentative
    char_count: int    # cumulative chars emitted so far in this utterance


class StreamingEngine:
    """Streams partial transcription hypotheses from an audio queue.

    Usage:
        engine = StreamingEngine(model, config)
        engine.start()
        # push np.ndarray chunks via engine.push(chunk)
        # read partials via engine.get_partial() (non-blocking, returns None if none ready)
        # call engine.commit() to get final text and reset
        engine.stop()
    """

    def __init__(
        self,
        model,                    # faster_whisper.WhisperModel
        partial_interval_ms: int = 300,
    ) -> None:
        self._model = model
        self._interval_s = partial_interval_ms / 1000.0
        self._lock = threading.Lock()
        self._buffer: list[np.ndarray] = []
        self._prev_hypothesis: str = ""
        self._last_emitted: str = ""
        self._cumulative_chars: int = 0
        self._pending_partial: PartialHypothesis | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background decode loop."""
        self._running = True
        self._buffer = []
        self._prev_hypothesis = ""
        self._last_emitted = ""
        self._cumulative_chars = 0
        self._pending_partial = None
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the decode loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def push(self, chunk: np.ndarray) -> None:
        """Push an audio chunk into the rolling buffer."""
        with self._lock:
            self._buffer.append(chunk)

    def get_partial(self) -> PartialHypothesis | None:
        """Return the latest partial hypothesis delta, or None if not ready."""
        with self._lock:
            result = self._pending_partial
            self._pending_partial = None
            return result

    def commit(self) -> str:
        """Stop streaming, decode final audio, return full final transcript."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        with self._lock:
            audio = _concat(self._buffer)
        if audio.size == 0:
            return ""
        return self._decode_once(audio)

    def reset(self) -> None:
        """Reset state for next utterance."""
        with self._lock:
            self._buffer = []
            self._prev_hypothesis = ""
            self._last_emitted = ""
            self._cumulative_chars = 0
            self._pending_partial = None
        self._running = False

    def _decode_loop(self) -> None:
        import time
        while self._running:
            time.sleep(self._interval_s)
            if not self._running:
                break
            with self._lock:
                audio = _concat(self._buffer)
            if audio.size < 3200:  # < 0.2 s — not enough audio yet
                continue
            hypothesis = self._decode_once(audio)
            with self._lock:
                stable_prefix = _common_prefix(self._prev_hypothesis, hypothesis)
                delta = stable_prefix[len(self._last_emitted):]
                if delta:
                    self._cumulative_chars += len(delta)
                    self._pending_partial = PartialHypothesis(
                        text=delta,
                        is_stable=True,
                        char_count=self._cumulative_chars,
                    )
                    self._last_emitted = stable_prefix
                self._prev_hypothesis = hypothesis

    def _decode_once(self, audio: np.ndarray) -> str:
        try:
            segments, _ = self._model.transcribe(audio, language="en")
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception as exc:
            log.debug("StreamingEngine decode error: %s", exc)
            return ""


def _concat(chunks: list[np.ndarray]) -> np.ndarray:
    if not chunks:
        return np.array([], dtype=np.float32)
    return np.concatenate(chunks)


def _common_prefix(a: str, b: str) -> str:
    """Return longest common prefix of two strings."""
    i = 0
    min_len = min(len(a), len(b))
    while i < min_len and a[i] == b[i]:
        i += 1
    return a[:i]
