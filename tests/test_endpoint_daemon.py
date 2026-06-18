"""Daemon-level pre-warm wiring for Ghost Ahead (spec-ghost-ahead, Phase 1).

Pre-warm is harmless: on a likely endpoint the daemon eagerly decodes the
streaming buffer so the post-release commit is warm. The authoritative transcript
still happens on real hold-release; nothing the user sees changes. Off by default
the anticipator is never constructed.
"""
from __future__ import annotations

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _PrewarmSpyEngine:
    def __init__(self):
        self.prewarm_calls = 0

    def prewarm(self):
        self.prewarm_calls += 1


def _daemon(endpoint_enabled, **endpoint_kw):
    cfg = Config()
    cfg.endpoint.enabled = endpoint_enabled
    cfg.endpoint.min_silence_s = endpoint_kw.get("min_silence_s", 0.3)
    cfg.endpoint.stable_updates = endpoint_kw.get("stable_updates", 1)
    cfg.endpoint.debounce_ms = endpoint_kw.get("debounce_ms", 500)
    d = Daemon(config=cfg, platform=get_platform())
    return d


def test_tick_is_noop_when_endpoint_disabled():
    d = _daemon(endpoint_enabled=False)
    assert d._endpoint is None
    # Tick must be safe even with no anticipator and no stream engine.
    assert d._endpoint_prewarm_tick("hello world", 0.5, now=1.0) is False


def test_endpoint_constructed_when_enabled():
    d = _daemon(endpoint_enabled=True)
    assert d._endpoint is not None


def test_tick_prewarms_on_likely_endpoint():
    d = _daemon(endpoint_enabled=True, stable_updates=1, debounce_ms=0)
    spy = _PrewarmSpyEngine()
    d._stream_engine = spy
    fired = d._endpoint_prewarm_tick("done speaking", 0.5, now=1.0)
    assert fired is True
    assert spy.prewarm_calls == 1


def test_tick_respects_debounce():
    d = _daemon(endpoint_enabled=True, stable_updates=1, debounce_ms=500)
    spy = _PrewarmSpyEngine()
    d._stream_engine = spy
    assert d._endpoint_prewarm_tick("done", 0.5, now=10.0) is True
    assert d._endpoint_prewarm_tick("done", 0.5, now=10.2) is False  # within debounce
    assert spy.prewarm_calls == 1


def test_tick_skips_prewarm_when_prewarm_disabled():
    d = _daemon(endpoint_enabled=True, stable_updates=1, debounce_ms=0)
    d._config.endpoint.prewarm = False
    spy = _PrewarmSpyEngine()
    d._stream_engine = spy
    assert d._endpoint_prewarm_tick("done", 0.5, now=1.0) is True
    assert spy.prewarm_calls == 0
