"""Inter-utterance continuation spacing.

The daemon injects each hold-to-talk burst independently, after stripping
leading/trailing whitespace (see ``clean_text`` and ``filter_transcript``).
With no separator, consecutive bursts glue together at the boundary:

    "words together" + "I mean" -> "words togetherI mean"

``continuation_prefix`` computes the separator to prepend before a burst that
continues a recent dictation. Policy: a single space, suppressed when the new
burst opens with closing punctuation (so we get "word." not "word .").
"""
from __future__ import annotations

# Closing punctuation that should hug the preceding word — never preceded by a
# space. Opening delimiters (quotes, "(", "[") are intentionally absent: a new
# clause starting with one still wants a leading space.
_NO_LEADING_SPACE_BEFORE = frozenset(".,!?;:)]}…%")


def continuation_prefix(text: str, *, had_recent_injection: bool) -> str:
    """Return the separator to prepend before injecting ``text``.

    Returns a single space when ``text`` continues a recent dictation burst,
    except when ``text`` begins with closing punctuation. Returns "" for the
    first burst of a session, for empty text, or before closing punctuation.
    """
    if not had_recent_injection or not text:
        return ""
    if text[0] in _NO_LEADING_SPACE_BEFORE:
        return ""
    return " "
