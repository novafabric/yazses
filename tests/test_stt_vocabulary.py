"""Built-in STT vocabulary — the app's own name is always primed into Whisper.

"YazSes" is a coined word Whisper has never seen, so it mis-transcribes the
spoken name ("yes ses", "yaz says", ...). `merge_initial_prompt` prepends a short
natural phrase containing the canonical spelling to every decode's
`initial_prompt`, merged ahead of the user's configured/personal vocabulary.
"""
from __future__ import annotations

from yazses.stt.vocabulary import APP_NAME, BUILTIN_PROMPT, merge_initial_prompt


def test_builtin_prompt_contains_app_name():
    assert APP_NAME in BUILTIN_PROMPT


def test_merge_always_includes_app_name_even_with_no_parts():
    merged = merge_initial_prompt()
    assert merged is not None
    assert APP_NAME in merged


def test_merge_includes_app_name_when_part_is_none_or_blank():
    merged = merge_initial_prompt(None, "   ", "")
    assert merged is not None
    assert APP_NAME in merged
    # No stray double spaces from the blank parts.
    assert "  " not in merged


def test_merge_preserves_user_prompt_after_builtin():
    merged = merge_initial_prompt("kubernetes terraform")
    assert APP_NAME in merged
    assert "kubernetes terraform" in merged
    # Built-in context comes first, user vocabulary after it.
    assert merged.index(APP_NAME) < merged.index("kubernetes")


def test_merge_joins_multiple_parts():
    merged = merge_initial_prompt("Notes.", "Kubernetes, kubectl")
    assert "Notes." in merged
    assert "Kubernetes, kubectl" in merged
