"""Offline disfluency filter — removes filler words, repetitions, and self-corrections."""
from __future__ import annotations
import re
from dataclasses import dataclass
from yazses.config import DisfluencyConfig


@dataclass
class FilterResult:
    text: str
    chars_removed: int


def filter_transcript(text: str, config: DisfluencyConfig | None = None) -> FilterResult:
    """Apply three-pass disfluency filter. Returns cleaned text and chars removed.

    Rule A: filler word removal (case-insensitive word boundary regex).
            Guard: do NOT remove tokens that contain uppercase, underscore, slash, or dot
            (those are proper nouns or code identifiers).
    Rule B: consecutive 2-gram deduplication (repeat until stable).
    Rule C: self-correction trigger detection — if found, remove from last sentence
            boundary before the trigger, through to end of trigger phrase.
    """
    if config is None:
        config = DisfluencyConfig()
    if not config.enabled or not text.strip():
        return FilterResult(text=text, chars_removed=0)

    original_len = len(text)

    # Rule A — filler word removal
    text = _remove_fillers(text, config.filler_words)

    # Rule B — 2-gram consecutive dedup
    text = _dedup_2grams(text)

    # Rule C — self-correction rollback
    text = _apply_self_corrections(text, config.self_correction_triggers)

    # Normalise multiple spaces
    text = re.sub(r'  +', ' ', text).strip()

    return FilterResult(text=text, chars_removed=max(0, original_len - len(text)))


def _is_protected(token: str) -> bool:
    """Return True if this token should NOT be altered (proper noun or code id)."""
    return bool(
        any(c.isupper() for c in token)
        or '_' in token
        or '/' in token
        or '.' in token
    )


def _remove_fillers(text: str, filler_words: list[str]) -> str:
    if not filler_words:
        return text
    # Sort longest first so multi-word fillers match before single words
    sorted_fillers = sorted(filler_words, key=len, reverse=True)
    pattern = re.compile(
        r'\b(' + '|'.join(re.escape(w) for w in sorted_fillers) + r')[,]?\s*',
        re.IGNORECASE,
    )

    def _replacer(m: re.Match) -> str:
        matched = m.group(0)
        token = m.group(1)
        # Protect uppercase / code tokens
        if _is_protected(token):
            return matched
        return ''

    return pattern.sub(_replacer, text)


def _dedup_2grams(text: str) -> str:
    """Remove second occurrence of consecutive identical 2-grams."""
    while True:
        tokens = text.split()
        changed = False
        i = 0
        result: list[str] = []
        while i < len(tokens):
            if (
                i + 3 < len(tokens)
                and tokens[i] == tokens[i + 2]
                and tokens[i + 1] == tokens[i + 3]
            ):
                result.append(tokens[i])
                result.append(tokens[i + 1])
                i += 4
                changed = True
            else:
                result.append(tokens[i])
                i += 1
        text = ' '.join(result)
        if not changed:
            break
    return text


def _apply_self_corrections(text: str, triggers: list[str]) -> str:
    if not triggers:
        return text
    lower = text.lower()
    for trigger in triggers:
        idx = lower.find(trigger.lower())
        if idx == -1:
            continue
        # Find last sentence boundary before the trigger
        boundary = max(
            text.rfind('. ', 0, idx),
            text.rfind('! ', 0, idx),
            text.rfind('? ', 0, idx),
        )
        if boundary == -1:
            # No sentence boundary — remove everything up to end of trigger
            end = idx + len(trigger)
            # Skip trailing whitespace/comma
            while end < len(text) and text[end] in ' ,':
                end += 1
            text = text[end:].strip()
        else:
            # Remove from after the boundary separator through end of trigger
            keep_end = boundary + 2  # keep '. '
            end = idx + len(trigger)
            while end < len(text) and text[end] in ' ,':
                end += 1
            text = text[:keep_end] + text[end:]
        lower = text.lower()
    return text
