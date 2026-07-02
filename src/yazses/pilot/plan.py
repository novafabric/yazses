"""AT-SPI Voice Pilot planning (pure) — ADR-v2-007.

Parse a spoken UI command ("click Save", "focus the terminal", "toggle dark
mode") and match its target against a list of accessibility-tree elements,
resolving ambiguity by a spoken ordinal ("the third") or flagging it for a
confirm. Actions are limited to a safe verb set. The pyatspi tree reader +
actioner are heavy + Linux-only and opt-in; this layer is fully testable with
plain data — no desktop, no screenshots.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Spoken verb → canonical, safe action.
_ACTIONS = {
    "click": "activate", "press": "activate", "activate": "activate", "tap": "activate",
    "focus": "focus", "select": "focus",
    "toggle": "toggle", "check": "toggle", "uncheck": "toggle",
}

_ORDINALS = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4,
    "1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4,
}

# Filler words dropped from the target/label so "click the Save button" → "save".
_STOP = frozenset("the a an button on to of my item option".split())


@dataclass(frozen=True)
class Element:
    label: str
    role: str = ""
    actions: tuple[str, ...] = ()     # supported actions (empty = unknown/any)


@dataclass(frozen=True)
class PilotCommand:
    action: str
    target: str
    ordinal: int | None = None


@dataclass(frozen=True)
class PilotPlan:
    action: str
    element: Element
    ambiguous: bool                   # a runner-up tied the top → confirm/ordinal
    score: float


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP}


def parse_command(phrase) -> PilotCommand | None:
    """Parse a spoken UI command into ``(action, target, ordinal)`` or ``None``."""
    norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (phrase or "").lower())).strip()
    if not norm:
        return None
    words = norm.split()
    action = _ACTIONS.get(words[0])
    if action is None:
        return None
    ordinal: int | None = None
    kept: list[str] = []
    for w in words[1:]:
        if w in _ORDINALS and ordinal is None:
            ordinal = _ORDINALS[w]
        else:
            kept.append(w)
    target = " ".join(w for w in kept if w not in _STOP).strip()
    if not target:
        return None
    return PilotCommand(action=action, target=target, ordinal=ordinal)


def _score(target: str, label: str) -> float:
    """Jaccard token overlap in [0, 1] between the target and an element label."""
    t, lab = _content_tokens(target), _content_tokens(label)
    if not t or not lab:
        return 0.0
    return len(t & lab) / len(t | lab)


def match_elements(target, elements, *, threshold: float = 0.5):
    """Return ``(element, score)`` candidates scoring ≥ threshold, best first."""
    scored = [(e, _score(target, e.label)) for e in elements]
    scored = [(e, s) for e, s in scored if s >= threshold]
    scored.sort(key=lambda es: es[1], reverse=True)
    return scored


def plan_action(phrase, elements, *, threshold: float = 0.5) -> PilotPlan | None:
    """Plan a UI action from a spoken command + the current element list.

    Returns ``None`` if the phrase isn't a pilot command or nothing matches. A
    spoken ordinal selects the Nth candidate; otherwise the top candidate is used
    and ``ambiguous`` is True when a runner-up ties the top score (so the caller
    asks for a confirm/ordinal). Pure and deterministic.
    """
    cmd = parse_command(phrase)
    if cmd is None:
        return None
    cands = match_elements(cmd.target, elements, threshold=threshold)
    if not cands:
        return None
    if cmd.ordinal is not None:
        if cmd.ordinal >= len(cands):
            return None
        elem, score = cands[cmd.ordinal]
        return PilotPlan(action=cmd.action, element=elem, ambiguous=False, score=score)
    top_elem, top_score = cands[0]
    ambiguous = len(cands) > 1 and abs(cands[1][1] - top_score) < 1e-9
    return PilotPlan(action=cmd.action, element=top_elem, ambiguous=ambiguous, score=top_score)
