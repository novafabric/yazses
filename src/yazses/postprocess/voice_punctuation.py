"""Spoken punctuation & formatting → symbols (opt-in).

When ``[commands] voice_punctuation`` is enabled, dictating the *name* of a
punctuation mark inserts the mark: "hello comma world period" → "hello, world.".
Off by default because the words also occur in ordinary speech ("a period of
time"), so it is only safe for users who opt in and adapt their phrasing.
"""
from __future__ import annotations

import re

# Multi-word phrases must be tried before shorter ones, so replacements are
# ordered longest-first within each group.

# Formatting phrases → literal (surrounding whitespace is absorbed).
_FORMATTING: list[tuple[str, str]] = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("newline", "\n"),
    ("tab key", "\t"),
]

# Punctuation that attaches to the preceding word: no space before, keep after.
# ("hello comma" → "hello,"). Alternatives share one symbol.
_ATTACH_LEFT: list[tuple[str, str]] = [
    ("full stop", "."),
    ("period", "."),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("semicolon", ";"),
    ("semi colon", ";"),
    ("colon", ":"),
    ("comma", ","),
]


def apply_voice_punctuation(text: str) -> str:
    """Replace spoken punctuation/formatting words with their symbols."""
    if not text:
        return text
    s = text
    for phrase, repl in _FORMATTING:
        s = re.sub(rf"\s*\b{re.escape(phrase)}\b\s*", repl, s, flags=re.IGNORECASE)
    for phrase, sym in _ATTACH_LEFT:
        # Absorb whitespace before the phrase so the symbol hugs the prior word;
        # whatever follows (usually a space) is preserved.
        s = re.sub(rf"\s*\b{re.escape(phrase)}\b", sym, s, flags=re.IGNORECASE)
    # Collapse any doubled spaces the substitutions produced.
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s
