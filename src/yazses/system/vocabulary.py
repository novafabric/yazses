"""Personal dictionary — words STT mis-hears, primed into Whisper's initial_prompt.

Stored one word/phrase per line in ``vocabulary.txt`` next to config.toml. The
daemon merges these into the STT ``initial_prompt`` so hard-to-recognise names are
spelled correctly. Managed with ``yazses vocab add/list/remove``.
"""
from __future__ import annotations

from pathlib import Path


def vocab_path(config_dir) -> Path:
    return Path(config_dir) / "vocabulary.txt"


def load_vocab(path) -> list[str]:
    """Return the dictionary words (order preserved), or [] if absent."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        w = line.strip()
        if w:
            out.append(w)
    return out


def add_vocab(path, words) -> list[str]:
    """Append *words* (case-insensitively de-duplicated), return the full list."""
    p = Path(path)
    existing = load_vocab(p)
    seen = {w.lower() for w in existing}
    for w in words:
        w = w.strip()
        if w and w.lower() not in seen:
            existing.append(w)
            seen.add(w.lower())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(existing) + ("\n" if existing else ""), encoding="utf-8")
    return existing


def remove_vocab(path, word) -> list[str]:
    """Remove *word* (case-insensitive), return the remaining list."""
    p = Path(path)
    remaining = [w for w in load_vocab(p) if w.lower() != word.strip().lower()]
    p.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
    return remaining
