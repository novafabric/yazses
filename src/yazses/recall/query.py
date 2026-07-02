"""Spoken Recall — rank past dictations by relevance to a spoken query (ADR-v2-005).

Pure: operates on lightweight records (anything exposing ``final_text``/``text``
and ``ts``, or a ``(text, ts)`` tuple), with no store or crypto import, so it is
fully testable. The daemon adapts encrypted-corpus ``EventRecord``s into inputs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Leading trigger phrases that turn a spoken utterance into a corpus query.
_RECALL_TRIGGERS = (
    "what did i say about",
    "what did i dictate about",
    "search my dictation for",
    "find in my notes",
    "recall",
)

# Function words that carry no retrieval signal.
_STOP = frozenset(
    "the a an and or of to in on at is are was were about my your for with "
    "that this it".split()
)


@dataclass
class RecallHit:
    """One ranked recall result: the transcript text, its timestamp, and score."""

    text: str
    ts: float
    score: float


def parse_recall(phrase: str) -> str | None:
    """Extract the recall query from a spoken phrase, or ``None`` if not a recall.

    Matches a leading trigger ("what did I say about X", "recall X") and returns
    the remaining query terms (possibly ``""`` when the trigger had no tail, which
    the caller may treat as "show most recent").
    """
    cleaned = phrase.strip().rstrip(".?!")
    low = cleaned.lower()
    for trig in _RECALL_TRIGGERS:
        if low == trig or low.startswith(trig + " "):
            return cleaned[len(trig):].strip()
    return None


def _tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 1 and t not in _STOP
    }


def _as_text_ts(rec) -> tuple[str, float]:
    if isinstance(rec, (tuple, list)):
        return str(rec[0] or ""), float(rec[1])
    text = getattr(rec, "final_text", None) or getattr(rec, "text", "") or ""
    return str(text), float(getattr(rec, "ts", 0.0) or 0.0)


def rank_events(records, query: str, *, limit: int = 5) -> list[RecallHit]:
    """Rank records by query-term overlap, tie-broken by recency (newest first).

    ``records`` is any iterable of ``(text, ts)`` tuples or objects exposing
    ``final_text``/``text`` + ``ts``. Score is the count of shared content tokens.
    With a non-empty query, zero-overlap records are dropped; with an empty query
    every record scores 0 so the newest ``limit`` are returned ("show recent").
    Pure and deterministic.
    """
    q = _tokens(query)
    hits: list[RecallHit] = []
    for rec in records:
        text, ts = _as_text_ts(rec)
        if not text.strip():
            continue
        overlap = len(q & _tokens(text)) if q else 0
        if q and overlap == 0:
            continue
        hits.append(RecallHit(text=text, ts=ts, score=float(overlap)))
    hits.sort(key=lambda h: (h.score, h.ts), reverse=True)
    return hits[: max(0, limit)]
