import numpy as np
import pytest

from yazses.config import LearningConfig
from yazses.learning.capture import CorpusWriter, build_writer
from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore


@pytest.fixture
def writer(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    store = CorpusStore(tmp_path, cipher)
    w = CorpusWriter(store)
    yield w
    w.stop()


def _event(**kw):
    base = {
        "raw_text": "hello",
        "cleaned_text": "hello",
        "filtered_text": "hello",
        "final_text": "hello",
        "injected": True,
    }
    base.update(kw)
    return base


def test_write_persists_via_background_thread(writer, tmp_path):
    writer.write(_event(raw_text="async world"))
    writer.flush()
    events = writer._store.events()
    assert len(events) == 1
    assert events[0].raw_text == "async world"


def test_write_with_audio(writer):
    audio = np.full(8000, 0.2, dtype=np.float32)
    writer.write(_event(), audio=audio, sample_rate=16000)
    writer.flush()
    eid = writer._store.last_event_id()
    assert writer._store.load_audio(eid) is not None


def test_write_never_raises_on_bad_event(writer):
    # A bad event must not propagate to the caller (hot path safety).
    writer.write(None)  # type: ignore[arg-type]
    writer.flush()  # worker swallows the failure
    assert writer._store.stats().count == 0


def test_mark_last_wrong(writer):
    writer.write(_event())
    writer.flush()
    assert writer.mark_last_wrong("corrected") is True
    assert writer._store.events()[0].correction_text == "corrected"


def test_redaction(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    store = CorpusStore(tmp_path, cipher)
    w = CorpusWriter(store, redact_patterns=(r"\d{3}-\d{2}-\d{4}",))
    try:
        w.write(_event(raw_text="my ssn is 123-45-6789 ok", final_text="123-45-6789"))
        w.flush()
        rec = store.events()[0]
        assert "123-45-6789" not in rec.raw_text
        assert "[REDACTED]" in rec.raw_text
        assert rec.final_text == "[REDACTED]"
    finally:
        w.stop()


def test_build_writer_disabled_returns_none(tmp_path):
    assert build_writer(tmp_path, LearningConfig(enabled=False)) is None


def test_build_writer_enabled(tmp_path):
    w = build_writer(tmp_path, LearningConfig(enabled=True))
    assert w is not None
    try:
        w.write(_event())
        w.flush()
        assert w._store.stats().count == 1
    finally:
        w.stop()
