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


def _event(ts):
    return {
        "ts": ts,
        "raw_text": "x",
        "cleaned_text": "x",
        "filtered_text": "x",
        "final_text": "x",
        "injected": True,
    }


def test_prune_by_age(store):
    now = time.time()
    store.add_event(_event(now - 40 * 86400))  # 40 days old
    store.add_event(_event(now - 5 * 86400))   # 5 days old
    removed = store.prune(retention_days=30, max_mb=500)
    assert removed == 1
    assert store.stats().count == 1


def test_prune_age_disabled_when_zero(store):
    now = time.time()
    store.add_event(_event(now - 999 * 86400))
    removed = store.prune(retention_days=0, max_mb=500)
    assert removed == 0
    assert store.stats().count == 1


def test_prune_by_size_drops_oldest_first(store):
    now = time.time()
    # ~0.5 MB of int16 PCM per clip (16000 * 16s = 256k samples * 2 bytes).
    big = np.full(256_000, 0.1, dtype=np.float32)
    first = store.add_event(_event(now - 100), audio=big)
    store.add_event(_event(now - 50), audio=big)
    store.add_event(_event(now), audio=big)
    assert store.stats().count == 3

    # Cap at 1 MB: oldest clips evicted until under the cap.
    store.prune(retention_days=0, max_mb=1)
    remaining = {e.id for e in store.events()}
    assert first not in remaining
    assert store.stats().size_bytes <= 1 * 1024 * 1024


def test_prune_size_disabled_when_zero(store):
    big = np.full(256_000, 0.1, dtype=np.float32)
    store.add_event(_event(time.time()), audio=big)
    removed = store.prune(retention_days=0, max_mb=0)
    assert removed == 0
    assert store.stats().count == 1
