import pytest

from yazses.learning.capture import open_store
from yazses.learning.edit_watch import EditWatcher


class _ImmediateTimer:
    """Fires synchronously on start() so tests don't sleep."""

    def __init__(self, _delay, fn, args=()):
        self._fn = fn
        self._args = args
        self.daemon = False

    def start(self):
        self._fn(*self._args)

    def is_alive(self):
        return False

    def cancel(self):
        pass


def _watcher(reader, sink):
    return EditWatcher(reader, sink, delay_s=0.0, timer_factory=_ImmediateTimer)


def test_in_place_correction_is_captured():
    captured = []
    w = _watcher(lambda: "the text", lambda inj, cur: captured.append((inj, cur)))
    w.watch("thetext")
    assert captured == [("thetext", "the text")]


def test_unchanged_text_not_captured():
    captured = []
    w = _watcher(lambda: "hello world", lambda inj, cur: captured.append((inj, cur)))
    w.watch("hello world")
    assert captured == []


def test_wholly_different_text_ignored():
    # User moved on and typed something unrelated — not a correction.
    captured = []
    w = _watcher(lambda: "completely unrelated sentence here", lambda i, c: captured.append((i, c)))
    w.watch("hello world")
    assert captured == []


def test_reader_returning_none_is_safe():
    captured = []
    w = _watcher(lambda: None, lambda i, c: captured.append((i, c)))
    w.watch("hello world")
    assert captured == []


def test_reader_exception_is_swallowed():
    def boom():
        raise RuntimeError("editor gone")

    w = _watcher(boom, lambda i, c: (_ for _ in ()).throw(AssertionError("should not fire")))
    w.watch("hello world")  # must not raise


def test_empty_injection_skipped():
    calls = []
    w = EditWatcher(lambda: calls.append("read") or "x", lambda i, c: None,
                    timer_factory=_ImmediateTimer)
    w.watch("")
    w.watch("   ")
    assert calls == []  # reader never invoked


def test_correction_persists_through_corpus(tmp_path):
    # End-to-end: a captured edit lands on the matching event in the store.
    store = open_store(tmp_path)
    store.add_event({
        "ts": 1.0, "raw_text": "thetext", "cleaned_text": "thetext",
        "filtered_text": "thetext", "final_text": "thetext", "injected": True,
    })
    w = _watcher(lambda: "the text", store.update_correction_for)
    w.watch("thetext")
    rec = store.events()[0]
    assert rec.correction_text == "the text"
    assert rec.edit_signal == pytest.approx(1.0)
    store.close()
