"""A panel's content starts below its title bar, and its header lines up
with the rows under it.

The title bars asked for 26 px but told the dock they wanted 21, and the
dock starts its content where the title bar's size hint ends. So both
panels ran 5 px under their title bars: the first layer row's highlight
in Layers, and the gold kind line in Properties, which lost its margin and
sat against the bar. The header's name also stood 4 px in while the rows
below it stood 8 px in, so the page opened slightly out of line.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (QApplication, QDockWidget, QListWidget,
                               QMainWindow)

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.dock_title import DockTitleBar
from serpentine3d.ui.icons import panel_icon
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.properties import PropertiesPanel


def test_a_dock_s_content_starts_under_its_title_bar():
    window = QMainWindow()
    dock = QDockWidget("Layers", window)
    bar = DockTitleBar(panel_icon("layers"), "Layers", dock)
    dock.setTitleBarWidget(bar)
    content = QListWidget()
    dock.setWidget(content)
    window.setCentralWidget(QListWidget())
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    window.resize(600, 400)
    window.show()
    QApplication.processEvents()
    try:
        assert content.geometry().top() > bar.geometry().bottom(), \
            (f"content starts at {content.geometry().top()} but the title "
             f"bar runs to {bar.geometry().bottom()}")
    finally:
        window.close()


def _layer_page():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    panel = LayersPanel(scene, history, selection=selection)
    props.follow_layers(panel)
    props.resize(300, 600)
    props.show()
    walls = scene.layers.create("Walls")
    scene.notify()
    QApplication.processEvents()
    for i in range(panel.tree.topLevelItemCount()):
        item = panel.tree.topLevelItem(i)
        item.setSelected(panel._layer_id(item) == walls.id)
    QApplication.processEvents()
    return props


def _text_left(label, page):
    """Where a label's text starts across the page, padding counted."""
    return label.mapTo(page, QPoint(label.contentsRect().x(), 0)).x()


def test_the_layer_header_lines_up_with_the_rows_under_it():
    props = _layer_page()
    page, head = props.layer_page, props.layer_head
    row = props.layer_form.labelForField(props.layer_name)
    rows_at = row.mapTo(page, QPoint(0, 0)).x()
    assert _text_left(head.title, page) == rows_at
    assert _text_left(head.detail, page) == rows_at
    assert head.mark.mapTo(page, QPoint(0, 0)).x() == rows_at


def _first_ink(page, label):
    """The first column, across the page, where a label puts down ink:
    where its text really starts, after anything Qt indents it by."""
    image = page.grab().toImage()
    top = label.mapTo(page, QPoint(0, 0)).y()
    background = image.pixelColor(1, top + label.height() // 2).lightness()
    for x in range(image.width() // 2):
        for y in range(top, top + label.height()):
            if abs(image.pixelColor(x, y).lightness() - background) > 60:
                return x
    return None


def test_the_header_s_text_starts_where_the_rows_text_does():
    """Padding lined up is not text lined up: a styled label indents its
    text half an x further unless told not to."""
    props = _layer_page()
    page, head = props.layer_page, props.layer_head
    row = props.layer_form.labelForField(props.layer_name)
    rows_at = _first_ink(page, row)
    assert abs(_first_ink(page, head.title) - rows_at) <= 1
    assert abs(_first_ink(page, head.detail) - rows_at) <= 1


def test_the_header_has_room_under_the_title_bar():
    props = _layer_page()
    head = props.layer_head
    assert head.mark.mapTo(props.layer_page, QPoint(0, 0)).y() >= 8


def test_the_empty_page_lines_up_too():
    scene = Scene()
    props = PropertiesPanel(scene, SelectionManager(scene), History(scene))
    props.resize(300, 600)
    props.show()
    QApplication.processEvents()
    page = props.object_head.parentWidget()
    row = props.form.labelForField(props.name_edit)
    assert (_text_left(props.object_head.title, page)
            == row.mapTo(page, QPoint(0, 0)).x())
