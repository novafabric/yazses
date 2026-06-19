"""`yazses doctor` reports Dysfluency-Friendly Mode status (ADR-015).

Mirrors the prosody-extra check: skipped entirely when the mode is off, an OK
line when it is enabled.
"""
from __future__ import annotations

from yazses.system.doctor import _dysfluency_check


def test_dysfluency_check_skipped_when_disabled():
    assert _dysfluency_check(False) is None


def test_dysfluency_check_ok_when_enabled():
    name, status, detail = _dysfluency_check(True)
    assert "dysfluency" in name.lower()
    assert status == "OK"
