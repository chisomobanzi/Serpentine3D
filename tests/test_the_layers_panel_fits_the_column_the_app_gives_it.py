"""Every layer column is on screen in the panel width a fresh window gives.

A fresh window hands Properties and Layers a 280px column (`PANEL_WIDTH`),
deliberately: extra window width belongs to the drawing, not to a panel of
fixed-content fields. The layers tree was laid out before it had Type and
Print columns, and with them added its five columns want more than 280 - so
in the shipped app the Print column sits entirely off the right-hand edge
behind a horizontal scrollbar, and Type is cut in half. A column you have
to scroll sideways to find is one nobody finds.

The name is the only column whose content has no natural width, so the name
is what gives: the four narrow columns keep the width their content needs
and the name takes whatever is left over.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from serpentine3d.app import PANEL_WIDTH, MainWindow
from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.linetype import LINETYPES
from serpentine3d.core.scene import Scene
from serpentine3d.ui import theme
from serpentine3d.ui.layers_panel import LayersPanel

NAME_COL = 0
TYPE_COL = 3
PRINT_COL = 4


def _panel(width=PANEL_WIDTH):
    scene = Scene()
    panel = LayersPanel(scene, History(scene))
    panel.resize(width, 300)
    panel.show()
    QApplication.processEvents()
    return scene, panel


def _item_for(panel, layer_id):
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        if panel._layer_id(item) == layer_id:
            return item
    raise AssertionError("no row for that layer")


def _columns(panel):
    tree = panel.tree
    return [tree.columnWidth(c) for c in range(tree.columnCount())]


def test_the_columns_fit_the_width_a_fresh_window_gives_the_panel():
    _scene, panel = _panel()
    tree = panel.tree
    total = sum(_columns(panel))
    assert total <= tree.viewport().width(), (
        f"the five columns want {total}px of the {tree.viewport().width()}px "
        "the panel column has")


def test_the_print_column_is_there_without_scrolling_sideways():
    _scene, panel = _panel()
    tree = panel.tree
    index = tree.indexFromItem(_item_for(panel, DEFAULT_LAYER_ID), PRINT_COL)
    assert tree.visualRect(index).right() <= tree.viewport().rect().right(), \
        "the Print cell starts past the right-hand edge of the panel"
    assert not tree.horizontalScrollBar().isVisible(), \
        "the layers tree needs a sideways scrollbar to show its own columns"


def test_the_room_left_over_goes_to_the_layer_name():
    _scene, narrow = _panel()
    _scene2, wide = _panel(PANEL_WIDTH + 120)
    assert wide.tree.columnWidth(NAME_COL) > narrow.tree.columnWidth(NAME_COL), \
        "a wider panel did not give the extra room to the layer name"


def test_widening_the_panel_leaves_the_narrow_columns_alone():
    """Type and Print are sized for their content, so more room is not
    theirs to take - a 200px-wide Print column would be a waste of a panel
    that only ever says "Default" or "0.25"."""
    _scene, narrow = _panel()
    _scene2, wide = _panel(PANEL_WIDTH + 120)
    assert _columns(narrow)[1:] == _columns(wide)[1:], \
        "widening the panel changed a column that has a content width"


# -- the window the app actually builds --

def test_the_columns_fit_the_dock_of_a_real_window_under_the_real_theme():
    """The one that caught it. A panel resized by a test proves nothing
    about the width the app gives it, and a panel built without the
    stylesheet proves nothing about the font it paints with: in the
    packaged build all five columns were on screen and "Continuous" still
    read "Continuo...". `run()` sets the theme, then builds the window, so
    do that.
    """
    app = QApplication.instance()
    was = app.styleSheet()
    app.setStyleSheet(theme.QSS)
    try:
        win = MainWindow()
        win.resize(1600, 900)
        win.show()
        QApplication.processEvents()
        panel = win.layers_panel
        panel.scene.layers.set_linetype(DEFAULT_LAYER_ID,
                                        max(LINETYPES, key=len))
        panel.scene.notify()
        QApplication.processEvents()
        tree = panel.tree
        try:
            assert sum(_columns(panel)) <= tree.viewport().width(), (
                f"the columns want {sum(_columns(panel))}px of the "
                f"{tree.viewport().width()}px the Layers dock has")
            assert not tree.horizontalScrollBar().isVisible(), \
                "the Layers dock needs a sideways scrollbar in a fresh window"
            for column, what in ((TYPE_COL, "Type"), (PRINT_COL, "Print")):
                needed = tree.sizeHintForColumn(column)
                assert tree.columnWidth(column) >= needed, (
                    f"the {what} column is {tree.columnWidth(column)}px "
                    f"where its rows need {needed}px, so it reads cut short")
            # The name column is the one that stretches, so it is the one
            # anything else takes its width out of. Sublayers gave every
            # row an indent for its expander, which is charged to this
            # column, and a fresh window's own layer came out as "Defa...".
            needed = tree.sizeHintForColumn(NAME_COL)
            assert tree.columnWidth(NAME_COL) >= needed, (
                f"the Layer column is {tree.columnWidth(NAME_COL)}px where "
                f"a fresh window's own layer needs {needed}px, so the name "
                f"of the layer everything is drawn on reads cut short")
        finally:
            win.mark_saved()
            win.close()
    finally:
        app.setStyleSheet(was)
