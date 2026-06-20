"""Biasing prompt builder (pure — no model, no training).

Composes Whisper's ``initial_prompt`` from the user vocabulary + frequent personal
terms mined from the corpus, so the recognizer favours the user's jargon and proper
nouns. The biased prompt is prepended/merged with any configured ``[stt] initial_prompt``.
"""
from __future__ import annotations

from collections import Counter

# Minimal stopword set — common function words that add no biasing value.
_STOPWORDS = frozenset(
    "the a an and or but is are was were be been to of in on at it this that "
    "for with as i you he she we they me my your his her our their now then "
    "do does did so if not no yes up down out".split()
)


def mine_terms(texts, top_k: int = 64, min_count: int = 2) -> list[str]:
    """Return up to ``top_k`` content words occurring at least ``min_count`` times.

    Stopwords and very short tokens are dropped; ordered most-frequent first.
    """
    counts: Counter[str] = Counter()
    for text in texts:
        for raw in (text or "").split():
            tok = raw.strip(".,!?;:\"'()[]{}")
            low = tok.lower()
            if len(low) > 2 and low not in _STOPWORDS:
                counts[low] += 1
    return [w for w, c in counts.most_common() if c >= min_count][:top_k]


def build_prompt(
    vocabulary,
    mined,
    *,
    existing_prompt: str = "",
    max_terms: int = 64,
) -> str:
    """Merge vocabulary + mined terms into ``existing_prompt`` (deduped, capped).

    Order: the existing prompt is kept verbatim at the front; then up to
    ``max_terms`` unique new terms (vocabulary first, then mined), de-duplicated
    case-insensitively against each other and the existing prompt.
    """
    seen = {w.lower() for w in existing_prompt.split()}
    chosen: list[str] = []
    for term in list(vocabulary) + list(mined):
        low = term.lower()
        if low in seen:
            continue
        seen.add(low)
        chosen.append(term)
        if len(chosen) >= max_terms:
            break
    if not chosen:
        return existing_prompt
    suffix = " ".join(chosen)
    return f"{existing_prompt} {suffix}".strip() if existing_prompt else suffix
