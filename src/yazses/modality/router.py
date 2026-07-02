"""Modality role routing (pure) — ADR-v2-011.

Given the currently-available input modalities and a role policy, decide which
modality owns each role and arbitrate conflicts by a priority order. Hardware
intake lives elsewhere; this layer is pure policy and fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass

# Canonical roles a modality can own.
ROLES = ("dictation", "command", "targeting", "activate")

# The role each modality is fastest at (Meta sEMG / gaze-HCI research).
_DEFAULT_ROLES = {
    "voice": "dictation",
    "emg": "command",
    "gaze": "targeting",
    "keyboard": "activate",
}

# Named presets: role maps for common setups.
PRESETS: dict[str, dict[str, str]] = {
    "balanced": dict(_DEFAULT_ROLES),
    "hands-free": {"voice": "dictation", "emg": "command", "gaze": "targeting"},
    "voice-only": {"voice": "dictation"},
}

_DEFAULT_PRIORITY = ("voice", "emg", "gaze", "keyboard")


@dataclass
class ModalityPolicy:
    roles: dict[str, str]              # modality -> role
    priority: tuple[str, ...]          # tie-break order when 2 modalities claim a role

    @classmethod
    def from_preset(cls, name: str, priority=None) -> "ModalityPolicy":
        """Build from a named preset (unknown → 'balanced')."""
        roles = dict(PRESETS.get(name, PRESETS["balanced"]))
        return cls(roles=roles, priority=tuple(priority or _DEFAULT_PRIORITY))


def resolve_roles(available, policy: ModalityPolicy) -> dict[str, str]:
    """Return ``role -> chosen modality`` for the available modalities.

    Each available modality proposes its configured role; when several claim the
    same role, the one earliest in ``policy.priority`` wins (modalities outside the
    priority list are considered last, in input order). Modalities with no role in
    the policy, or not available, are ignored. Pure and deterministic.
    """
    avail_set = list(dict.fromkeys(available))  # de-dupe, keep order
    ordered = [m for m in policy.priority if m in avail_set]
    ordered += [m for m in avail_set if m not in ordered]
    out: dict[str, str] = {}
    for m in ordered:
        role = policy.roles.get(m)
        if role and role not in out:
            out[role] = m
    return out


def route_action(action_role: str, available, policy: ModalityPolicy) -> str | None:
    """Which modality should handle an action of ``action_role``, or ``None``."""
    return resolve_roles(available, policy).get(action_role)
