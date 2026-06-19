"""`yazses doctor` reports prosody-extra availability (spec-prosody-ink).

The spec requires doctor to report whether the optional `prosody` extra
(parselmouth) is importable when `[prosody] enabled`, mirroring the EMG
serial-port check. Absent → WARN (pause→¶ still works, emphasis is disabled),
not FAIL. When prosody is off the check is skipped entirely.
"""
from __future__ import annotations

import sys

from yazses.system.doctor import _prosody_check


def test_prosody_check_skipped_when_disabled():
    assert _prosody_check(False) is None


def test_prosody_check_warns_when_extra_absent(monkeypatch):
    # Force the import to fail regardless of what's installed.
    monkeypatch.setitem(sys.modules, "parselmouth", None)
    name, status, detail = _prosody_check(True)
    assert "prosody" in name.lower()
    assert status == "WARN"
    assert "extra" in detail.lower() or "install" in detail.lower()


def test_prosody_check_ok_when_extra_importable(monkeypatch):
    # Inject a stand-in module so the import succeeds.
    import types

    monkeypatch.setitem(sys.modules, "parselmouth", types.ModuleType("parselmouth"))
    name, status, detail = _prosody_check(True)
    assert status == "OK"
