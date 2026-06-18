"""Ghost Ahead -> endpoint anticipation (P1 core).

The original "predict the next words" seed is a field gap (free-form spoken
*content* prediction is undemonstrated; even code ghost-text is ~2/3 rejected).
The shipped pivot is endpoint anticipation: predict *when* the speaker is about
to stop, so the daemon can pre-warm the model or speculatively finalize and hide
release latency — while the authoritative transcript always stays on the real
hold-release, so a wrong early guess can never truncate the user.

This module is the decision core: it watches successive partial transcripts plus
trailing-silence duration and signals a likely endpoint. Wiring it into the
streaming decode loop (``stt/streaming.py``) is a later phase. Spec:
design/specs/ghost-ahead.md.
"""
from __future__ import annotations


class EndpointAnticipator:
    """Signal a likely end-of-utterance from partial-transcript stability + silence."""

    def __init__(
        self,
        min_silence_s: float = 0.3,
        stable_updates: int = 2,
        debounce_s: float = 0.0,
    ):
        self._min_silence_s = min_silence_s
        self._stable_updates = stable_updates
        self._debounce_s = debounce_s
        self._last: str | None = None
        self._stable = 0
        self._last_fire: float | None = None

    def reset(self) -> None:
        self._last = None
        self._stable = 0
        self._last_fire = None

    def observe(self, partial: str, silence_s: float, now: float | None = None) -> bool:
        """Feed the latest partial transcript and trailing silence.

        Returns True when the partial has held steady for ``stable_updates``
        observations and trailing silence has reached ``min_silence_s`` — the
        moment to pre-warm / speculatively finalize. When ``now`` is supplied and
        ``debounce_s`` is set, fires within ``debounce_s`` of the previous fire are
        suppressed (anti-thrash on micro-pauses; spec-ghost-ahead LOFA-4). Omitting
        ``now`` disables debounce, preserving the original two-arg behaviour.
        """
        text = (partial or "").strip()
        if not text:
            self._last = None
            self._stable = 0
            return False

        if text == self._last:
            self._stable += 1
        else:
            self._last = text
            self._stable = 1

        fires = self._stable >= self._stable_updates and silence_s >= self._min_silence_s
        if not fires:
            return False

        if now is not None and self._debounce_s > 0.0 and self._last_fire is not None:
            if now - self._last_fire < self._debounce_s:
                return False
        if now is not None:
            self._last_fire = now
        return True
