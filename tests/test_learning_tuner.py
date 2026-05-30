import time
import tomllib

import numpy as np
import pytest

from yazses.config import Config
from yazses.learning.analysis import load_few_shots
from yazses.learning.crypto import Cipher, load_or_create_key
from yazses.learning.store import CorpusStore
from yazses.learning.tuner import run_tune


@pytest.fixture
def store(tmp_path):
    cipher = Cipher(load_or_create_key(tmp_path / "data"))
    s = CorpusStore(tmp_path / "data", cipher)
    yield s
    try:
        s.close()
    except Exception:
        pass


def _ev(**kw):
    base = {
        "ts": time.time(), "raw_text": "", "cleaned_text": "",
        "filtered_text": "", "final_text": "", "injected": True,
    }
    base.update(kw)
    return base


def _capture(messages):
    return messages.append


def test_tune_dry_run_changes_nothing(store, tmp_path):
    store.add_event(_ev(raw_text="cubernetes", correction_text="kubernetes", wrong_flag=True))
    store.add_event(_ev(raw_text="cubernetes again", correction_text="kubernetes again", wrong_flag=True))
    config_path = tmp_path / "config.toml"
    msgs: list[str] = []

    applied = run_tune(
        store, Config(), config_path, tmp_path / "few_shots.toml",
        do_apply=False, do_retranscribe=False, transcribe_fn=None,
        echo=_capture(msgs), confirm=lambda _q: True,
    )
    assert applied == []
    assert not config_path.exists()  # nothing written on dry run
    assert any("Dry run" in m for m in msgs)


def test_tune_apply_writes_config(store, tmp_path):
    store.add_event(_ev(raw_text="use terriform", correction_text="use terraform", wrong_flag=True))
    store.add_event(_ev(raw_text="run terriform", correction_text="run terraform", wrong_flag=True))
    config_path = tmp_path / "config.toml"

    applied = run_tune(
        store, Config(), config_path, tmp_path / "few_shots.toml",
        do_apply=True, do_retranscribe=False, transcribe_fn=None,
        echo=lambda _m: None, confirm=lambda _q: True,
    )
    assert applied
    data = tomllib.loads(config_path.read_text())
    assert "terraform" in data["stt"]["initial_prompt"]


def test_tune_apply_respects_decline(store, tmp_path):
    store.add_event(_ev(raw_text="cubernetes", correction_text="kubernetes", wrong_flag=True))
    store.add_event(_ev(raw_text="cubernetes too", correction_text="kubernetes too", wrong_flag=True))
    config_path = tmp_path / "config.toml"

    applied = run_tune(
        store, Config(), config_path, tmp_path / "few_shots.toml",
        do_apply=True, do_retranscribe=False, transcribe_fn=None,
        echo=lambda _m: None, confirm=lambda _q: False,  # decline everything
    )
    assert applied == []
    assert not config_path.exists()


def test_tune_with_retranscribe(store, tmp_path):
    audio = np.full(4000, 0.1, dtype=np.float32)
    store.add_event(_ev(raw_text="hello wrold"), audio=audio)
    store.add_event(_ev(raw_text="anuther won"), audio=audio)
    store.add_event(_ev(raw_text="thurd mistak"), audio=audio)
    msgs: list[str] = []

    run_tune(
        store, Config(), tmp_path / "config.toml", tmp_path / "few_shots.toml",
        do_apply=False, do_retranscribe=True,
        transcribe_fn=lambda a, sr: "totally different words here",
        echo=_capture(msgs), confirm=lambda _q: True,
    )
    assert any("Re-transcribed 3" in m for m in msgs)
    # High divergence on a small/base model should surface a model-upgrade proposal.
    assert any("model" in m.lower() or "Upgrade" in m for m in msgs)


def test_tune_few_shots_apply(store, tmp_path):
    eid = store.add_event(_ev(raw_text="save the planet", intent_type="edit",
                              intent_action="save"))
    store.mark_wrong(eid)  # wrong_flag is only ever set via mark_wrong, as in the daemon
    fs_path = tmp_path / "few_shots.toml"

    run_tune(
        store, Config(), tmp_path / "config.toml", fs_path,
        do_apply=True, do_retranscribe=False, transcribe_fn=None,
        echo=lambda _m: None, confirm=lambda _q: True,
    )
    loaded = load_few_shots(fs_path)
    assert any("save the planet" in line for line in loaded)


def test_tune_no_proposals(store, tmp_path):
    store.add_event(_ev(raw_text="clean text", final_text="clean text"))
    msgs: list[str] = []
    applied = run_tune(
        store, Config(), tmp_path / "config.toml", tmp_path / "few_shots.toml",
        do_apply=True, do_retranscribe=False, transcribe_fn=None,
        echo=_capture(msgs), confirm=lambda _q: True,
    )
    assert applied == []
    assert any("No tuning proposals" in m for m in msgs)
