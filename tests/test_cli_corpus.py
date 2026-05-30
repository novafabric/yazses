import time
import types

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.ipc.client import IpcUnreachableError
from yazses.learning.capture import open_store

runner = CliRunner()


def _fake_platform(tmp_path, ipc_client=None):
    paths = types.SimpleNamespace(
        data_dir=tmp_path,
        config_file=tmp_path / "config.toml",
        ipc_socket=tmp_path / "daemon.sock",
    )
    return types.SimpleNamespace(
        paths=paths,
        ipc_client_factory=lambda _sock: ipc_client,
    )


def _seed_corpus(tmp_path):
    store = open_store(tmp_path)
    store.add_event({
        "ts": time.time(), "raw_text": "hello", "cleaned_text": "hello",
        "filtered_text": "hello", "final_text": "hello", "injected": True,
    })
    store.add_event({
        "ts": time.time(), "raw_text": "", "discard_reason": "silent",
        "level": 0.001, "injected": False,
    })
    store.close()


# ---- mark-wrong -----------------------------------------------------------

def test_mark_wrong_success(tmp_path, monkeypatch):
    client = types.SimpleNamespace(call=lambda method, **kw: {"ok": True})
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path, client))
    result = runner.invoke(cli.app, ["mark-wrong", "-c", "hello world"])
    assert result.exit_code == 0
    assert "Flagged" in result.output


def test_mark_wrong_daemon_down(tmp_path, monkeypatch):
    def _boom(method, **kw):
        raise IpcUnreachableError("nope")

    client = types.SimpleNamespace(call=_boom)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path, client))
    result = runner.invoke(cli.app, ["mark-wrong"])
    assert result.exit_code == 1
    assert "not running" in result.output


# ---- corpus status / forget / destroy ------------------------------------

def test_corpus_status_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "status"])
    assert result.exit_code == 0
    assert "No corpus yet" in result.output


def test_corpus_status_populated(tmp_path, monkeypatch):
    _seed_corpus(tmp_path)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "status"])
    assert result.exit_code == 0
    assert "events:    2" in result.output
    assert "1 discarded" in result.output


def test_corpus_destroy_requires_flag(tmp_path, monkeypatch):
    _seed_corpus(tmp_path)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "destroy"])
    assert result.exit_code == 1
    assert (tmp_path / "corpus.db").exists()  # untouched


def test_corpus_destroy(tmp_path, monkeypatch):
    _seed_corpus(tmp_path)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "destroy", "--i-mean-it"])
    assert result.exit_code == 0
    assert not (tmp_path / "corpus.db").exists()


def test_corpus_forget(tmp_path, monkeypatch):
    _seed_corpus(tmp_path)
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["corpus", "forget", "--minutes", "60"])
    assert result.exit_code == 0
    assert "Forgot 2 event" in result.output


# ---- tune (dry run, no model) ---------------------------------------------

def test_tune_no_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["tune", "--no-retranscribe"])
    assert result.exit_code == 1
    assert "No corpus yet" in result.output


def test_tune_dry_run(tmp_path, monkeypatch):
    store = open_store(tmp_path)
    for _ in range(2):
        store.add_event({
            "ts": time.time(), "raw_text": "cubernetes pod",
            "correction_text": "kubernetes pod", "cleaned_text": "cubernetes pod",
            "filtered_text": "cubernetes pod", "final_text": "cubernetes pod",
            "injected": True,
        })
    store.close()
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(tmp_path))
    result = runner.invoke(cli.app, ["tune", "--no-retranscribe"])
    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert "kubernetes" in result.output
    assert not (tmp_path / "config.toml").exists()
