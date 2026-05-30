"""Pre-speech ring buffer — prepends recent audio to capture voice onset.

People with hypophonia (ALS, Parkinson's) often have delayed voice onset:
their speech starts soft and ramps up. Without pre-speech padding, the first
0.1–0.5 s of the utterance is lost. This ring buffer retains the last N ms
of audio and prepends it to each recording.
"""
from __future__ import annotations

import numpy as np


class PreSpeechRingBuffer:
    """Fixed-duration ring buffer for pre-speech audio padding.

    Usage:
        buf = PreSpeechRingBuffer(padding_ms=200, sample_rate=16000)
        # During idle: call buf.push(chunk) with each audio chunk
        # On hold start: call buf.get() to get the padding to prepend
    """

    def __init__(self, padding_ms: int = 200, sample_rate: int = 16000) -> None:
        self._capacity = int(padding_ms * sample_rate / 1000)
        self._sample_rate = sample_rate
        self._buffer: np.ndarray = np.zeros(self._capacity, dtype=np.float32)
        self._head = 0
        self._filled = False

    def push(self, chunk: np.ndarray) -> None:
        """Add audio chunk to the ring buffer."""
        if self._capacity == 0 or chunk.size == 0:
            return
        flat = chunk.flatten().astype(np.float32)
        n = flat.size
        if n >= self._capacity:
            # Chunk larger than capacity — keep only the last capacity samples
            self._buffer[:] = flat[-self._capacity:]
            self._head = 0
            self._filled = True
            return
        end = self._head + n
        if end <= self._capacity:
            self._buffer[self._head:end] = flat
        else:
            split = self._capacity - self._head
            self._buffer[self._head:] = flat[:split]
            self._buffer[:end - self._capacity] = flat[split:]
            self._filled = True
        self._head = end % self._capacity
        if self._head == 0:
            self._filled = True

    def get(self) -> np.ndarray:
        """Return the buffered pre-speech audio as a contiguous array."""
        if self._capacity == 0:
            return np.array([], dtype=np.float32)
        if not self._filled:
            if self._head == 0:
                return np.array([], dtype=np.float32)
            return self._buffer[:self._head].copy()
        # Re-order: from head to end, then 0 to head
        return np.concatenate([self._buffer[self._head:], self._buffer[:self._head]])

    def prepend_padding(self, audio: np.ndarray) -> np.ndarray:
        """Prepend buffered pre-speech audio to recorded audio."""
        padding = self.get()
        if padding.size == 0:
            return audio
        return np.concatenate([padding, audio])

    def clear(self) -> None:
        """Reset the buffer."""
        self._buffer[:] = 0.0
        self._head = 0
        self._filled = False
