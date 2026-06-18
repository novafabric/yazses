"""Mid-Thought Undo (P1) — treat reformulation as a first-class signal.

"scratch that" / "no, make it..." let a speaker take back what they just said
instead of dictating their hesitation literally. P1 ships the reliable template
layer only: whole-utterance "scratch that"-class commands that delete the last
burst YazSes itself injected (via backspaces — works in any text field, unlike
an editor-undo keystroke). Open-ended rewrite ("no, make it X") is gated to P2
(TERTiUS caps free-form spoken edits at 30-55%; design/specs/mid-thought-undo.md).

Buffer-ownership invariant: the ledger only ever counts characters YazSes
injected, so "scratch that" can never delete the user's own typing.
"""
from __future__ import annotations

import re
from collections import deque

# Whole-utterance "scratch that"-family commands (normalized: lower, stripped,
# trailing sentence punctuation removed). Anchored so a trigger appearing inside
# ordinary prose ("scratch the surface", "scratch that itch") never fires.
_SCRATCH_RE = re.compile(
    r"^(?:no[, ]+)?(?:scratch|delete|cancel) (?:that|this|last)$"
)


def parse_revise(text: str) -> str | None:
    """Return the revise op name for a whole-utterance scratch command, else None."""
    if not text:
        return None
    norm = text.strip().lower().rstrip(".?!,").strip()
    if _SCRATCH_RE.match(norm):
        return "scratch_last"
    return None


class DictationLedger:
    """LIFO record of YazSes-injected dictation bursts (char count + text).

    The char counts drive "scratch that" (Mid-Thought Undo); the parallel text
    record drives Punch-In re-record (spec-punch-in), which needs the actual span
    to align a respoken correction against. Both honour the buffer-ownership
    invariant: only text YazSes itself injected is ever tracked.
    """

    def __init__(self, max_history: int = 50):
        self._counts: deque[int] = deque(maxlen=max_history)
        self._texts: deque[str] = deque(maxlen=max_history)

    def __len__(self) -> int:
        return len(self._counts)

    def record(self, text: str) -> None:
        """Remember an injected burst by its character count and text (ignores empty)."""
        if text:
            self._counts.append(len(text))
            self._texts.append(text)

    def scratch_last(self) -> int:
        """Pop and return the char count of the most recent burst (0 if none)."""
        if not self._counts:
            return 0
        if self._texts:
            self._texts.pop()
        return self._counts.pop()

    def last_text(self) -> str:
        """Return the most recent burst's text without popping it ("" if none)."""
        return self._texts[-1] if self._texts else ""

    def replace_last(self, text: str) -> None:
        """Replace the most recent burst's text + count in place (no-op if empty)."""
        if not self._texts or not self._counts:
            return
        self._texts[-1] = text
        self._counts[-1] = len(text)
