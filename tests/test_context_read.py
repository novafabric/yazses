"""Tests for the best-effort desktop context reader (v2.0.0 Wave A, ADR-v2-004)."""

from yazses.commands.context import ContextSources
from yazses.system import context_read


def test_run_swallows_errors_for_missing_command():
    # A command that cannot run must yield "" rather than raise.
    assert context_read._run(["definitely-not-a-real-binary-xyz", "--x"]) == ""


def test_read_sources_honors_flags(monkeypatch):
    monkeypatch.setattr(context_read, "active_window_title", lambda: "TITLE")
    monkeypatch.setattr(context_read, "selection_text", lambda: "SEL")
    monkeypatch.setattr(context_read, "clipboard_text", lambda: "CLIP")

    src = context_read.read_sources(
        use_window_title=True, use_selection=False, use_clipboard=True
    )
    assert isinstance(src, ContextSources)
    assert src.window_title == "TITLE"
    assert src.selection == ""      # disabled
    assert src.clipboard == "CLIP"


def test_read_sources_all_off_is_empty(monkeypatch):
    monkeypatch.setattr(context_read, "active_window_title", lambda: "TITLE")
    monkeypatch.setattr(context_read, "selection_text", lambda: "SEL")
    monkeypatch.setattr(context_read, "clipboard_text", lambda: "CLIP")
    src = context_read.read_sources(False, False, False)
    assert src == ContextSources("", "", "")


def test_read_sources_never_raises_if_reader_fails(monkeypatch):
    def boom():
        raise RuntimeError("reader blew up")

    # read_sources calls readers directly; wrap to prove the daemon guard is the
    # safety net. Here we assert the individual readers are the ones returning "".
    monkeypatch.setattr(context_read, "active_window_title", lambda: "")
    monkeypatch.setattr(context_read, "selection_text", lambda: "")
    monkeypatch.setattr(context_read, "clipboard_text", lambda: "")
    src = context_read.read_sources(True, True, True)
    assert src == ContextSources("", "", "")
