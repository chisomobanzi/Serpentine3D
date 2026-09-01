"""A layer's Type and Print drop-downs open wide enough to read.

The Type and Print columns were sized by eye, narrower than the longest
thing they hold, so opening either one gave a drop-down with its own text
cut off: "Continuous" came up as "Contin" with the arrow eating the rest.
A list you cannot read is no better than the click-to-cycle cell it
replaced - you can see that a choice is being made, but not which one. The
cell should show its value whole, and the open drop-down should show every
choice in it whole.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QAbstractItemDelegate, QApplication, QComboBox

from serpentine3d.core.history import History
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.linetype import LINETYPES
from serpentine3d.core.scene import Scene
from serpentine3d.ui import theme
from serpentine3d.ui.layers_panel import LayersPanel

TYPE_COL = 3
PRINT_COL = 4


def _panel(width=400):
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


def _open_editor(panel, layer_id, column):
    """Double-click the cell and hand back the drop-down it opens."""
    index = panel.tree.indexFromItem(_item_for(panel, layer_id), column)
    pos = QPointF(panel.tree.visualRect(index).center())
    for typ in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(panel.tree.viewport(), QMouseEvent(
            typ, pos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    QApplication.processEvents()
    # The one on screen, not the first one ever made: a closed editor is
    # hidden and deleted later, so it can still answer findChild and hand
    # back a drop-down belonging to a column nobody is editing.
    open_combos = [c for c in panel.tree.findChildren(QComboBox)
                   if c.isVisible()]
    assert open_combos, "editing the cell opened no drop-down"
    assert len(open_combos) == 1, "more than one drop-down is open"
    return open_combos[0]


def _close_editor(panel, layer_id, column, combo):
    """End the edit. No test may leave a cell editor open."""
    index = panel.tree.indexFromItem(_item_for(panel, layer_id), column)
    delegate = panel.tree.itemDelegateForIndex(index)
    delegate.closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)
    QApplication.processEvents()


def _widest(strings, widget):
    fm = widget.fontMetrics()
    return max(fm.horizontalAdvance(s) for s in strings)


def _themed_panel():
    """A panel under the stylesheet the shipped app runs with.

    `run()` sets the theme on the QApplication before it builds the window,
    but Qt only resolves a stylesheet's font onto a widget when that widget
    is polished, which is after its constructor. A column measured in the
    constructor is therefore measured against a font the tree will not
    paint with.
    """
    app = QApplication.instance()
    was = app.styleSheet()
    app.setStyleSheet(theme.QSS)
    try:
        yield _panel()
    finally:
        app.setStyleSheet(was)


# -- the open drop-down --

def test_the_type_drop_down_opens_wide_enough_for_its_longest_linetype():
    _scene, panel = _panel()
    combo = _open_editor(panel, DEFAULT_LAYER_ID, TYPE_COL)
    wanted = combo.sizeHint().width()
    assert combo.width() >= wanted, (
        f"the linetype drop-down opened {combo.width()}px wide but needs "
        f"{wanted}px to show '{max(LINETYPES, key=len)}' and its arrow")
    _close_editor(panel, DEFAULT_LAYER_ID, TYPE_COL, combo)


def test_the_print_drop_down_opens_wide_enough_for_its_longest_width():
    _scene, panel = _panel()
    combo = _open_editor(panel, DEFAULT_LAYER_ID, PRINT_COL)
    wanted = combo.sizeHint().width()
    assert combo.width() >= wanted, (
        f"the print width drop-down opened {combo.width()}px wide but needs "
        f"{wanted}px to show 'Default' and its arrow")
    _close_editor(panel, DEFAULT_LAYER_ID, PRINT_COL, combo)


def _assert_inside_the_tree(panel, column):
    """Widening the editor must not push it off the right-hand edge, where
    the half of it that matters would be the half you cannot see."""
    combo = _open_editor(panel, DEFAULT_LAYER_ID, column)
    viewport = panel.tree.viewport()
    overhang = combo.geometry().right() - viewport.rect().right()
    assert overhang <= 0, (
        f"the drop-down runs {overhang}px past the right edge of the tree")
    assert combo.geometry().left() >= viewport.rect().left(), \
        "the drop-down starts off the left edge of the tree"
    _close_editor(panel, DEFAULT_LAYER_ID, column, combo)


def test_an_open_type_drop_down_stays_inside_the_panel():
    _scene, panel = _panel()
    _assert_inside_the_tree(panel, TYPE_COL)


def test_an_open_print_drop_down_stays_inside_the_panel():
    """The one at risk. Print is the last column and the columns fill the
    panel exactly, so its editor has nothing to its right to grow into."""
    _scene, panel = _panel()
    tree = panel.tree
    index = tree.indexFromItem(_item_for(panel, DEFAULT_LAYER_ID), PRINT_COL)
    assert tree.visualRect(index).right() >= tree.viewport().rect().right(), \
        "Print is no longer the column that ends at the edge of the tree"
    _assert_inside_the_tree(panel, PRINT_COL)


# -- the cell you are not editing --

def _assert_not_elided(panel, column, what):
    """The column is at least as wide as the view says its rows need.

    `sizeHintForColumn` asks the delegate that actually paints the cell, so
    it counts the margins the style adds - which is the difference between
    "Continuous" and "Continuo...".
    """
    tree = panel.tree
    needed = tree.sizeHintForColumn(column)
    assert tree.columnWidth(column) >= needed, (
        f"the {what} column is {tree.columnWidth(column)}px where its own "
        f"rows need {needed}px, so the text is cut short")


def test_the_type_column_is_wide_enough_to_name_a_linetype():
    scene, panel = _panel()
    scene.layers.set_linetype(DEFAULT_LAYER_ID, max(LINETYPES, key=len))
    panel.rebuild()
    _assert_not_elided(panel, TYPE_COL, "Type")


def test_the_print_column_is_wide_enough_to_say_default():
    _scene, panel = _panel()
    _assert_not_elided(panel, PRINT_COL, "Print")


def test_the_columns_fit_the_font_the_app_theme_puts_on_them():
    """The shipped app sets 13px in its stylesheet, and a column measured
    against the default font before that landed showed "Continuo..."."""
    for _scene, panel in _themed_panel():
        panel.scene.layers.set_linetype(DEFAULT_LAYER_ID,
                                        max(LINETYPES, key=len))
        panel.rebuild()
        _assert_not_elided(panel, TYPE_COL, "Type")
        _assert_not_elided(panel, PRINT_COL, "Print")
