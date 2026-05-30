import time

import numpy as np
import pytest

from yazses.config import Config
from yazses.learning.analysis import (
    Proposal,
    analyze,
    apply_proposal,
    retranscribe,
    set_toml_key,
    toml_literal,
    word_distance,
)
from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore


@pytest.fixture
def store(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path))
    s = CorpusStore(tmp_path, cipher)
    yield s
    s.close()


def _ev(**kw):
    base = {
        "ts": time.time(),
        "raw_text": "",
        "cleaned_text": "",
        "filtered_text": "",
        "final_text": "",
        "injected": True,
    }
    base.update(kw)
    return base


# ---- word_distance --------------------------------------------------------

def test_word_distance_identical():
    assert word_distance("hello world", "hello world") == 0.0


def test_word_distance_both_empty():
    assert word_distance("", "") == 0.0


def test_word_distance_disjoint():
    assert word_distance("a b", "x y z") == pytest.approx(1.0)


def test_word_distance_partial():
    # one of two words differs
    assert word_distance("hello world", "hello there") == pytest.approx(0.5)


# ---- retranscribe ---------------------------------------------------------

def test_retranscribe_sets_distance(store):
    audio = np.full(4000, 0.1, dtype=np.float32)
    eid = store.add_event(_ev(raw_text="hello wrold"), audio=audio)

    def fake_transcribe(_audio, _sr):
        return "hello world"

    n = retranscribe(store, fake_transcribe)
    assert n == 1
    rec = [e for e in store.events() if e.id == eid][0]
    assert rec.retx_text == "hello world"
    assert rec.retx_distance == pytest.approx(0.5)


def test_retranscribe_skips_events_without_audio(store):
    store.add_event(_ev(raw_text="no audio"))
    assert retranscribe(store, lambda a, s: "x") == 0


# ---- VAD proposal ---------------------------------------------------------

def test_propose_vad_threshold():
    cfg = Config()
    cfg.accessibility.vad_threshold = 0.02
    events = [
        # accepted speech at level 0.04
        _rec(injected=True, level=0.04),
        _rec(injected=True, level=0.05),
        # dropped as silent though clearly speech-ish
        _rec(discard_reason="silent", injected=False, level=0.015),
    ]
    props = {p.kind: p for p in analyze(events, cfg)}
    assert "vad_threshold" in props
    assert props["vad_threshold"].value < 0.02
    assert props["vad_threshold"].section == "accessibility"


def test_no_vad_proposal_without_silent_discards():
    cfg = Config()
    events = [_rec(injected=True, level=0.04)]
    assert "vad_threshold" not in {p.kind for p in analyze(events, cfg)}


# ---- model proposal -------------------------------------------------------

def test_propose_model_upgrade():
    cfg = Config()
    cfg.stt.model = "base.en"
    events = [_rec(retx_distance=0.3) for _ in range(4)]
    props = {p.kind: p for p in analyze(events, cfg)}
    assert "model" in props
    assert props["model"].value == cfg.learning.tune_model


def test_no_model_proposal_when_accurate():
    cfg = Config()
    events = [_rec(retx_distance=0.02) for _ in range(4)]
    assert "model" not in {p.kind for p in analyze(events, cfg)}


# ---- vocabulary proposal --------------------------------------------------

def test_propose_vocabulary_from_corrections():
    cfg = Config()
    events = [
        _rec(raw_text="lets use cubernetes", correction_text="lets use kubernetes", wrong_flag=True),
        _rec(raw_text="deploy on cubernetes", correction_text="deploy on kubernetes", wrong_flag=True),
    ]
    props = {p.kind: p for p in analyze(events, cfg)}
    assert "vocabulary" in props
    assert "kubernetes" in props["vocabulary"].value


# ---- disfluency proposal --------------------------------------------------

def test_propose_disfluency_from_removed_words():
    cfg = Config()
    events = [
        _rec(raw_text="so anyway lets go", correction_text="lets go", wrong_flag=True),
        _rec(raw_text="anyway start now", correction_text="start now", wrong_flag=True),
    ]
    props = {p.kind: p for p in analyze(events, cfg)}
    assert "disfluency" in props
    assert "anyway" in props["disfluency"].value


# ---- few-shot proposal ----------------------------------------------------

def test_propose_few_shots_for_misfired_command():
    cfg = Config()
    events = [
        _rec(raw_text="save the world", intent_type="edit", intent_action="save", wrong_flag=True),
    ]
    props = {p.kind: p for p in analyze(events, cfg)}
    assert "few_shots" in props
    assert props["few_shots"].target == "few_shots"
    assert "save the world" in props["few_shots"].examples[0]


# ---- TOML writing ---------------------------------------------------------

def test_toml_literal_types():
    assert toml_literal(0.5) == "0.5"
    assert toml_literal("hi") == '"hi"'
    assert toml_literal(True) == "true"
    assert toml_literal(["a", "b"]) == '["a", "b"]'


def test_set_toml_key_creates_file(tmp_path):
    path = tmp_path / "config.toml"
    set_toml_key(path, "stt", "model", "small.en")
    import tomllib
    assert tomllib.loads(path.read_text())["stt"]["model"] == "small.en"


def test_set_toml_key_replaces_existing(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[accessibility]\nvad_threshold = 0.02\n")
    set_toml_key(path, "accessibility", "vad_threshold", 0.005)
    import tomllib
    assert tomllib.loads(path.read_text())["accessibility"]["vad_threshold"] == 0.005


def test_set_toml_key_inserts_into_existing_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[stt]\nmodel = \"base.en\"\n")
    set_toml_key(path, "stt", "initial_prompt", "kubernetes terraform")
    import tomllib
    data = tomllib.loads(path.read_text())
    assert data["stt"]["model"] == "base.en"
    assert data["stt"]["initial_prompt"] == "kubernetes terraform"


def test_apply_few_shots(tmp_path):
    fs = tmp_path / "few_shots.toml"
    prop = Proposal(kind="few_shots", title="t", detail="d", evidence=1,
                    target="few_shots", examples=['"save the world" -> {}'])
    apply_proposal(prop, tmp_path / "config.toml", fs)
    assert "save the world" in fs.read_text()


# ---- helper to build EventRecord without a DB -----------------------------

def _rec(**kw):
    from yazses.learning.store import EventRecord
    base = dict(
        id=1, ts=time.time(), audio_secs=1.0, decode_ms=50.0, model="base.en",
        level=None, sample_rate=16000, intent_type="dictate", intent_action="inject",
        injected=True, discard_reason=None, wrong_flag=False, edit_signal=None,
        retx_distance=None, has_audio=False, raw_text="", cleaned_text="",
        filtered_text="", final_text="", correction_text="", retx_text="",
    )
    base.update(kw)
    return EventRecord(**base)
