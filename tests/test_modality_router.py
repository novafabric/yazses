"""Modality Role Router (ADR-v2-011) — pure policy routing."""
from __future__ import annotations

from yazses.modality.router import (
    PRESETS,
    ModalityPolicy,
    resolve_roles,
    route_action,
)


def test_from_preset_balanced_defaults():
    p = ModalityPolicy.from_preset("balanced")
    assert p.roles["voice"] == "dictation"
    assert p.roles["emg"] == "command"
    assert p.roles["gaze"] == "targeting"


def test_from_preset_unknown_falls_back_to_balanced():
    assert ModalityPolicy.from_preset("bogus").roles == PRESETS["balanced"]


def test_resolve_roles_maps_available_modalities():
    p = ModalityPolicy.from_preset("balanced")
    roles = resolve_roles(["voice", "emg", "gaze"], p)
    assert roles == {"dictation": "voice", "command": "emg", "targeting": "gaze"}


def test_resolve_ignores_unavailable_and_unmapped():
    p = ModalityPolicy.from_preset("voice-only")
    # only voice has a role in this preset; emg present but unmapped → ignored
    assert resolve_roles(["voice", "emg"], p) == {"dictation": "voice"}


def test_priority_breaks_role_conflicts():
    # two modalities both mapped to 'command'; priority decides the winner
    p = ModalityPolicy(
        roles={"emg": "command", "keyboard": "command"},
        priority=("keyboard", "emg"),
    )
    assert resolve_roles(["emg", "keyboard"], p)["command"] == "keyboard"
    p2 = ModalityPolicy(
        roles={"emg": "command", "keyboard": "command"},
        priority=("emg", "keyboard"),
    )
    assert resolve_roles(["emg", "keyboard"], p2)["command"] == "emg"


def test_route_action_returns_modality_or_none():
    p = ModalityPolicy.from_preset("balanced")
    assert route_action("dictation", ["voice", "emg"], p) == "voice"
    assert route_action("targeting", ["voice", "emg"], p) is None  # no gaze available


def test_resolve_dedupes_available():
    p = ModalityPolicy.from_preset("balanced")
    roles = resolve_roles(["voice", "voice"], p)
    assert roles == {"dictation": "voice"}
