"""TTS backend Protocol (spec-read-back-loop).

No third-party import here so this module is always importable — the concrete
engines (kokoro, melo, …) live behind the optional ``tts`` extra.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class TtsBackend(Protocol):
    """Synthesize and play text on-device, sentence by sentence."""

    @property
    def name(self) -> str:
        """Stable backend id (e.g. ``kokoro``, ``null``) for status/logging."""
        ...

    def synthesize(self, text: str) -> Iterator[bytes]:
        """Yield PCM/WAV audio chunks for *text*, first chunk as early as possible."""
        ...

    def speak(self, text: str) -> None:
        """Synthesize and play *text*, blocking until done (or until cancel())."""
        ...

    def cancel(self) -> None:
        """Stop any in-progress playback immediately (barge-in)."""
        ...
