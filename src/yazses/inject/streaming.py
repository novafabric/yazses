"""StreamingInjector — tracks partial text cursor for correction-on-commit (ADR-004).

Usage:
    si = StreamingInjector(injector)
    si.inject_partial("hel")    # injects "hel", _chars_injected = 3
    si.inject_partial("lo ")    # injects "lo ", _chars_injected = 6
    si.commit("hello world")    # Shift+Left ×6, then inject "hello world"
    # or:
    si.cancel()                 # backspace ×6 to remove partial
"""
from __future__ import annotations

import logging

from yazses.platform.base import InjectorBackend

log = logging.getLogger(__name__)


class StreamingInjector:
    """Wraps an InjectorBackend with cursor-tracking for streaming correction."""

    def __init__(self, injector: InjectorBackend) -> None:
        self._injector = injector
        self._chars_injected: int = 0

    @property
    def chars_injected(self) -> int:
        return self._chars_injected

    def inject_partial(self, text: str) -> None:
        """Inject partial text and track character count."""
        if not text:
            return
        self._injector.inject(text)
        self._chars_injected += len(text)

    def commit(self, final_text: str) -> None:
        """Select all partial text (Shift+Left ×N) and replace with final_text.

        If _chars_injected is 0, just injects final_text directly.
        """
        if self._chars_injected > 0:
            # Select all injected partial characters
            self._injector.inject_key_sequence(
                ["shift+Left"] * self._chars_injected
            )
        self._injector.inject(final_text)
        self._chars_injected = 0

    def cancel(self) -> None:
        """Remove all partial text by injecting backspaces."""
        if self._chars_injected > 0:
            self._injector.inject_backspaces(self._chars_injected)
        self._chars_injected = 0

    def reset(self) -> None:
        """Reset counter without injecting anything (e.g. after error)."""
        self._chars_injected = 0
