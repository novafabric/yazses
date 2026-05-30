import time

import numpy as np
import pytest

from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore


@pytest.fixture
def store(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    s = CorpusStore(tmp_path, cipher)
    yield s
    s.close()


def _event(**kw):
    base = {
        "ts": time.time(),
        "audio_secs": 1.2,
        "decode_ms": 80.0,
        "model": "base.en",
        "level": 0.05,
        "raw_text": "hello wrold",
        "cleaned_text": "hello wrold",
        "filtered_text": "hello wrold",
        "final_text": "hello wrold",
        "intent_type": "dictate",
        "intent_action": "inject",
        "injected": True,
    }
    base.update(kw)
    return base


def test_add_and_read_back_decrypts_text(store):
    eid = store.add_event(_event(raw_text="quick brown fox"))
    events = store.events()
    assert len(events) == 1
    assert events[0].id == eid
    assert events[0].raw_text == "quick brown fox"
    assert events[0].injected is True


def test_text_is_encrypted_on_disk(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    store = CorpusStore(tmp_path, cipher)
    store.add_event(_event(raw_text="SENSITIVE SECRET PHRASE"))
    store.close()
    raw = (tmp_path / "corpus.db").read_bytes()
    assert b"SENSITIVE SECRET PHRASE" not in raw


def test_audio_roundtrip(store):
    audio = (np.sin(np.linspace(0, 20, 16000)) * 0.3).astype(np.float32)
    eid = store.add_event(_event(), audio=audio, sample_rate=16000)
    loaded = store.load_audio(eid)
    assert loaded is not None
    pcm, sr = loaded
    assert sr == 16000
    assert pcm.shape[0] == audio.shape[0]
    # 16-bit PCM roundtrip is lossy but close.
    assert np.max(np.abs(pcm - audio)) < 1e-3


def test_audio_clip_encrypted_on_disk(store, tmp_path):
    audio = np.full(8000, 0.2, dtype=np.float32)
    eid = store.add_event(_event(), audio=audio)
    clip = tmp_path / "clips" / f"{eid}.wav.enc"
    assert clip.exists()
    # Encrypted: no RIFF/WAVE magic header in the file.
    assert clip.read_bytes()[:4] != b"RIFF"


def test_no_audio_when_not_provided(store):
    eid = store.add_event(_event())
    assert store.load_audio(eid) is None
    assert store.events()[0].has_audio is False


def test_mark_wrong_defaults_to_last(store):
    store.add_event(_event())
    last = store.add_event(_event())
    assert store.mark_wrong(correction="hello world") is True
    events = {e.id: e for e in store.events()}
    assert events[last].wrong_flag is True
    assert events[last].correction_text == "hello world"


def test_mark_wrong_empty_store(store):
    assert store.mark_wrong() is False


def test_last_event_id(store):
    assert store.last_event_id() is None
    a = store.add_event(_event())
    b = store.add_event(_event())
    assert store.last_event_id() == b > a


def test_set_retx(store):
    eid = store.add_event(_event())
    store.set_retx(eid, "hello world", 0.4)
    rec = store.events()[0]
    assert rec.retx_text == "hello world"
    assert rec.retx_distance == pytest.approx(0.4)


def test_discard_event_recorded(store):
    store.add_event(_event(discard_reason="silent", injected=False, raw_text=""))
    s = store.stats()
    assert s.count == 1
    assert s.discarded == 1


def test_stats(store):
    store.add_event(_event())
    store.add_event(_event(discard_reason="empty"))
    store.add_event(_event())
    store.mark_wrong()
    s = store.stats()
    assert s.count == 3
    assert s.discarded == 1
    assert s.wrong == 1
    assert s.size_bytes > 0
    assert s.oldest_ts is not None and s.newest_ts is not None


def test_forget_recent(store):
    now = time.time()
    store.add_event(_event(ts=now - 3600))  # 1h ago
    store.add_event(_event(ts=now))          # now
    removed = store.forget(minutes=10)
    assert removed == 1
    assert store.stats().count == 1


def test_destroy(store, tmp_path):
    audio = np.full(4000, 0.1, dtype=np.float32)
    store.add_event(_event(), audio=audio)
    store.destroy()
    assert not (tmp_path / "corpus.db").exists()
    assert not list((tmp_path / "clips").glob("*.wav.enc"))
