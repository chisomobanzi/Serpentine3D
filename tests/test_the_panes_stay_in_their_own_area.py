"""The viewport panes live in their own area, never in the main window's.

The panes are docks of an inner window that is the main window's centre, and
the panels are docks of the main window. Before that inner window existed the
panes were the main window's docks, so a layout saved back then names them.
Qt 6.12 began looking for a saved dock among every widget inside a window,
not just its own, so restoring that old layout pulled the panes out into the
main window's left dock area. The inner window was left empty in the middle,
and since the centre takes whatever width is spare, maximising opened a gap
between the panes and the panels, with two edges to drag where there should
be one.

The suite may run an older Qt, so `qt_6_12` makes the main window's restore
claim the panes the way 6.12 does.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow

from serpentine3d.app import MainWindow

LEFT = Qt.DockWidgetArea.LeftDockWidgetArea
NOWHERE = Qt.DockWidgetArea.NoDockWidgetArea


@pytest.fixture
def old_layout(_qapp):
    """A main window layout that names the panes as its own docks."""
    w = MainWindow()
    for dock in w._viewport_docks():
        w.addDockWidget(LEFT, dock)
    w.cfg.set("window", "state", bytes(w.saveState().toBase64()).decode())
    w.cfg.save()
    w.close()


@pytest.fixture
def qt_6_12(monkeypatch):
    """Qt 6.12's restore: a dock the layout names is taken from wherever in
    the window it is."""
    def restore(self, state):
        saved = bytes(state)
        for dock in self.findChildren(QDockWidget):
            name = dock.objectName().encode("utf-16-be")
            if name and dock.parent() is not self and name in saved:
                self.addDockWidget(LEFT, dock)
        return QMainWindow.restoreState(self, state)
    monkeypatch.setattr(MainWindow, "restoreState", restore)


def _assert_panes_at_home(w):
    for dock in w._viewport_docks():
        assert dock.parent() is w.viewport_area, dock.objectName()
        assert w.dockWidgetArea(dock) == NOWHERE, dock.objectName()
        assert w.viewport_area.dockWidgetArea(dock) == LEFT, dock.objectName()
        assert dock.isVisibleTo(w.viewport_area), dock.objectName()


def test_an_old_layout_leaves_the_panes_in_their_own_area(old_layout, qt_6_12):
    w = MainWindow()
    try:
        _assert_panes_at_home(w)
    finally:
        w.close()


def test_so_does_the_layout_saved_after_it(old_layout, qt_6_12):
    first = MainWindow()
    first._remember_window()
    first.close()

    second = MainWindow()
    try:
        _assert_panes_at_home(second)
    finally:
        second.close()
