"""Headless smoke test for the Qt rendering layer.

Skipped entirely when PySide6 isn't installed (the `overlay` extra). Uses the
offscreen Qt platform so it runs in CI without a display.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.overlay.animation import Ripple  # noqa: E402
from yazses.overlay.widget import SonarWidget  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _paint(widget):
    # grab() runs paintEvent into a pixmap — exercises the full render path.
    return widget.grab()


def test_widget_constructs_with_expected_size(qapp):
    w = SonarWidget(220, "#00e5ff")
    assert w.width() == 220
    assert w.height() == 220


def test_widget_renders_ripples_without_crashing(qapp):
    w = SonarWidget(220, "#00e5ff")
    ripples = [
        Ripple(radius_frac=0.2, alpha=0.8, intensity=0.5),
        Ripple(radius_frac=0.7, alpha=0.3, intensity=1.0),
    ]
    w.set_ripples(ripples, core_intensity=0.6)
    pixmap = _paint(w)
    assert not pixmap.isNull()


def test_widget_renders_empty_state(qapp):
    w = SonarWidget(220, "#00e5ff")
    w.set_ripples([], core_intensity=0.0)
    assert not _paint(w).isNull()


def test_widget_tolerates_invalid_accent(qapp):
    w = SonarWidget(220, "not-a-color")
    w.set_ripples([Ripple(radius_frac=0.5, alpha=0.5, intensity=0.5)], 0.5)
    assert not _paint(w).isNull()


def test_widget_move_to(qapp):
    w = SonarWidget(220, "#00e5ff")
    w.move_to((100, 150))
    assert w.x() == 100
    assert w.y() == 150
