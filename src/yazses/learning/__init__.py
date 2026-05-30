"""Opt-in self-improvement loop (v0.5.0, ADR-012).

Captures dictation events to a local, encrypted corpus and turns them into
proposed config diffs via ``yazses tune``. Entirely dormant unless
``[learning] enabled = true``. Nothing here ever transmits data off the machine.
"""
