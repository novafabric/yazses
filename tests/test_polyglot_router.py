"""True Code-Switch routing decision layer (ADR-v2-008) — pure PolyglotRouter."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.polyglot.router import PolyglotRouter


@dataclass
class _Cfg:
    enabled: bool = False
    pair: str = ""
    adapter_path: str = ""
    mer_gate: float = 0.0


def test_inactive_by_default():
    r = PolyglotRouter.from_config(_Cfg())
    assert r.active is False
    assert r.should_route(["fa", "en"]) is False


def test_active_requires_enabled_pair_and_adapter():
    # enabled + pair but no adapter -> dormant (out-of-band model absent)
    r = PolyglotRouter.from_config(_Cfg(enabled=True, pair="fa-en"))
    assert r.active is False
    assert r.status_reason() == "set [polyglot] adapter_path to a code-switch adapter (out-of-band)"
    # fully configured -> active
    r2 = PolyglotRouter.from_config(_Cfg(enabled=True, pair="fa-en", adapter_path="/m/adapter"))
    assert r2.active is True
    assert r2.status_reason() is None
    assert r2.pair == ("fa", "en")


def test_invalid_pair_degrades_gracefully():
    r = PolyglotRouter.from_config(_Cfg(enabled=True, pair="nonsense", adapter_path="/m/a"))
    assert r.pair is None
    assert r.active is False
    assert r.status_reason() == "set [polyglot] pair to a valid code like 'fa-en'"


def test_disabled_has_no_status_reason():
    assert PolyglotRouter.from_config(_Cfg(pair="fa-en")).status_reason() is None


def test_should_route_needs_code_switch_within_pair():
    r = PolyglotRouter.from_config(_Cfg(enabled=True, pair="fa-en", adapter_path="/m/a"))
    assert r.should_route(["fa", "en"]) is True     # both pair langs present
    assert r.should_route(["en", "en"]) is False    # monolingual
    assert r.should_route(["fa", "de"]) is False    # de is outside the pair


def test_mer_gate_requires_minority_fraction():
    r = PolyglotRouter.from_config(
        _Cfg(enabled=True, pair="fa-en", adapter_path="/m/a", mer_gate=0.4)
    )
    # 1 fa out of 5 in-pair = 0.2 < 0.4 -> below gate
    assert r.should_route(["en", "en", "en", "en", "fa"]) is False
    # 2 fa out of 5 = 0.4 >= 0.4 -> routes
    assert r.should_route(["en", "en", "en", "fa", "fa"]) is True
