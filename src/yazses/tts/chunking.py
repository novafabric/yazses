"""Sentence chunking for streaming TTS (spec-read-back-loop).

Splitting the transcript into sentences lets the backend start speaking chunk 1
while chunk 2 synthesizes — the metric that matters is time-to-first-audio, not
full-utterance latency. Pure stdlib ``re``, no third-party dependency.
"""
from __future__ import annotations

import re
from collections.abc import Iterator

# Split after sentence-ending punctuation (. ! ?) followed by whitespace. The
# punctuation is kept with its sentence. A trailing fragment with no terminal
# punctuation is yielded as its own chunk.
_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


def sentence_chunks(text: str) -> Iterator[str]:
    """Yield ``text`` sentence by sentence, skipping empty/whitespace pieces."""
    if not text or not text.strip():
        return
    for piece in _BOUNDARY.split(text.strip()):
        chunk = piece.strip()
        if chunk:
            yield chunk
