"""Voice-to-Tool planning + confirmation guard (pure) — ADR-v2-006.

Map a spoken intent to a structured tool call against an allowlisted registry and
decide whether it needs confirmation before running. The offline SLM that emits
GBNF-constrained calls and the MCP client that executes them are heavy + opt-in
(behind the ``agent`` extra); this layer is fully testable with no model or network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CONFIRM_POLICIES = ("all", "writes", "none")


@dataclass(frozen=True)
class ToolSpec:
    """A callable tool the user can invoke by voice."""

    name: str
    triggers: tuple[str, ...]        # spoken phrases that select this tool
    writes: bool = False             # mutates state → confirm under 'writes' policy
    description: str = ""


@dataclass(frozen=True)
class ToolCall:
    """A planned invocation: the tool, the trailing argument, and a match score."""

    tool: str
    argument: str
    score: float


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def plan_tool(phrase, tools, *, allowlist=None) -> ToolCall | None:
    """Match a spoken phrase to the best allowlisted tool, or ``None``.

    Each tool's trigger phrases are matched at word boundaries; the longest trigger
    (most words, then most characters) wins, so specific commands beat generic
    ones. The utterance text after the matched trigger becomes the argument. Tools
    absent from a non-empty ``allowlist`` are skipped. Pure and deterministic.
    """
    norm = _norm(phrase)
    if not norm:
        return None
    allow = set(allowlist) if allowlist else None
    best: ToolCall | None = None
    best_key: tuple[int, int] = (0, 0)
    for tool in tools:
        if allow is not None and tool.name not in allow:
            continue
        for trig in tool.triggers:
            t = _norm(trig)
            if not t:
                continue
            m = re.search(rf"(?:^| ){re.escape(t)}(?: |$)", norm)
            if not m:
                continue
            key = (len(t.split()), len(t))
            if key > best_key:
                best_key = key
                best = ToolCall(
                    tool=tool.name,
                    argument=norm[m.end():].strip(),
                    score=float(len(t.split())),
                )
    return best


def needs_confirm(call, tools, policy: str = "writes") -> bool:
    """Whether a planned call must be confirmed before running.

    ``none`` → never; ``all`` → always; ``writes`` (default) → only if the tool is
    marked state-mutating. An unknown policy is treated as the safe ``all``.
    """
    if policy == "none":
        return False
    if policy == "all" or policy not in _CONFIRM_POLICIES:
        return True
    spec = next((t for t in tools if t.name == call.tool), None)
    return bool(spec and spec.writes)
