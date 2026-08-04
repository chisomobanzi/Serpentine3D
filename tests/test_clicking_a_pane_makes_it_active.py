"""Clicking in a viewport makes it the one commands act on.

The window carried two `eventFilter` methods: one to notice a click in a
pane, one to notice a panel splitter being dragged. The second definition
is the only one Python keeps, so the click half had never run. Every pane
but Perspective was therefore live to draw in and dead to everything that
asks which pane you are in — the CPlane a command draws on, the properties
and display panels, and the direction a typed length runs along.
"""

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow


def _quad():
    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("quad")
    QApplication.processEvents()
    return w


def _pane(w, name):
    return [v for v in w.all_viewports() if v._view_name == name][0]


def _click(vp, px=50.0, py=50.0):
    """A press delivered the way Qt delivers one, through the filters."""
    QApplication.sendEvent(vp, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(px, py),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))


def test_a_click_in_the_top_pane_makes_it_the_active_one():
    w = _quad()
    top = _pane(w, "top")
    assert w.ctx.viewport is not top, "the test proves nothing otherwise"
    _click(top)
    assert w.active_viewport is top
    assert w.ctx.viewport is top, \
        "commands were still acting on the pane nobody had clicked"


def test_every_pane_takes_its_turn():
    w = _quad()
    for name in ("front", "right", "top", "perspective"):
        pane = _pane(w, name)
        _click(pane)
        assert w.ctx.viewport is pane, name


def test_the_splitter_still_notices_a_panel_being_resized():
    """The other half of the filter, which is why there were two."""
    w = _quad()
    w._settled_width = w.width()
    w._settling = False
    w._panel_width = None
    dock = w._prop_dock
    assert not dock.isFloating() and dock.isVisibleTo(w)
    QApplication.sendEvent(dock, QResizeEvent(QSize(317, 400),
                                              QSize(300, 400)))
    assert w._panel_width == 317
