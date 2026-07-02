"""Confidence Ink & Voice Re-pick (v2.0.0 Wave A, ADR-v2-001).

faster-whisper exposes a per-word probability when decoded with word timestamps
(and a per-segment ``avg_logprob``). Unlike an LLM's verbalized confidence, these
ASR probabilities are a *calibrated* uncertainty signal. This module is pure logic
over ``(word, probability)`` data so it is unit-testable without a model: it flags
low-confidence words, groups them into contiguous spans, renders markers for the
overlay, and helps re-pick a flagged word from n-best alternatives.

Nothing here changes the injected text unless the user acts on a flag.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WordConfidence:
    text: str
    probability: float
    low: bool


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def annotate_words(
    words: list[tuple[str, float]], threshold: float
) -> list[WordConfidence]:
    """Tag each ``(word, probability)`` with whether it is at/below ``threshold``.

    Probabilities and the threshold are clamped to ``[0, 1]``. A word exactly at the
    threshold is flagged (``low=True``), matching the "at/below" contract.
    """
    t = _clamp01(threshold)
    return [
        WordConfidence(text=text, probability=(p := _clamp01(prob)), low=p <= t)
        for text, prob in words
    ]


def low_confidence_spans(
    words: list[tuple[str, float]], threshold: float
) -> list[tuple[int, int]]:
    """Return contiguous ``[start, end)`` index ranges of low-confidence words."""
    annotated = annotate_words(words, threshold)
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, w in enumerate(annotated):
        if w.low and start is None:
            start = i
        elif not w.low and start is not None:
            spans.append((start, i))
            start = None
    if start is not None:
        spans.append((start, len(annotated)))
    return spans


def mark_text(
    words: list[tuple[str, float]],
    threshold: float,
    prefix: str = "⟨",
    suffix: str = "⟩",
) -> str:
    """Render the words as one string with low-confidence words wrapped.

    Intended for overlay display / diagnostics — never for injection.
    """
    annotated = annotate_words(words, threshold)
    return " ".join(
        f"{prefix}{w.text}{suffix}" if w.low else w.text for w in annotated
    )


def repick(alternatives: list[str], current: str) -> str | None:
    """Return the next distinct alternative after ``current`` (wrapping).

    ``alternatives`` is the beam n-best for a span (most-likely first). Returns
    ``None`` when there is nothing to switch to (empty or single-choice list). If
    ``current`` is not among the alternatives, returns the most-likely one.
    """
    uniq: list[str] = []
    for a in alternatives:
        if a not in uniq:
            uniq.append(a)
    if len(uniq) <= 1:
        return None
    try:
        idx = uniq.index(current)
    except ValueError:
        return uniq[0]
    return uniq[(idx + 1) % len(uniq)]
