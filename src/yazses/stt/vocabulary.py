"""Built-in vocabulary always primed into Whisper's ``initial_prompt``.

``YazSes`` is a coined word the speech model has never seen in training, so it
mis-transcribes the spoken name ("yes ses", "yaz says", "yacht says", ...).
Whisper's ``initial_prompt`` is preceding *context* — listing the canonical
spelling biases the decoder toward it without forcing it into the output. We keep
the phrase short and neutral so it primes the name without making the model
hallucinate "YazSes" into unrelated speech.

:func:`merge_initial_prompt` is the single place that composes the effective
prompt: the built-in phrase first, then any configured/personal vocabulary.
"""
from __future__ import annotations

APP_NAME = "YazSes"

# A short natural sentence primes Whisper better than a bare token (it sees the
# word in context and in its canonical capitalisation).
BUILTIN_PROMPT = "The app is called YazSes."


def merge_initial_prompt(*parts: str | None) -> str | None:
    """Compose the effective ``initial_prompt`` from the built-in name vocabulary
    plus any extra parts (configured ``[stt] initial_prompt``, personal vocab).

    The built-in phrase always comes first; blank/``None`` parts are dropped.
    Always returns a non-empty string (the built-in name is always present), so
    callers never get ``None`` — but the signature mirrors the optional prompts
    they pass in.
    """
    chunks: list[str] = [BUILTIN_PROMPT]
    for part in parts:
        if part and part.strip():
            chunks.append(part.strip())
    merged = " ".join(chunks).strip()
    return merged or None
