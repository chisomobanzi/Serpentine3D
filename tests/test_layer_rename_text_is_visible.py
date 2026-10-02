"""A layer's inline rename field must leave room for a complete line (#52)."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QLineEdit, QStyle, QStyleFactory, QStyleOptionFrame,
)

from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.ui.layers_panel import LayersPanel
from serpentine3d.ui.theme import QSS


@pytest.fixture
def rename_panel():
    app = QApplication.instance()
    original_style = app.style().objectName()
    panels = []

    def make(style="Fusion", font_size=13):
        app.setStyle(QStyleFactory.create(style))
        scene = Scene()
        panel = LayersPanel(scene, History(scene))
        panels.append(panel)
        panel.setStyleSheet(QSS.replace("font-size: 13px;",
                                       f"font-size: {font_size}px;"))
        panel.resize(600, 300)
        panel.show()
        app.processEvents()
        panel._rename(scene.layers.current_id)
        app.processEvents()
        return scene, panel, panel.tree.findChild(QLineEdit)

    yield make
    for panel in panels:
        editor = panel.tree.findChild(QLineEdit)
        if editor is not None:
            QTest.keyClick(editor, Qt.Key.Key_Escape)
        panel.close()
        panel.deleteLater()
    app.processEvents()
    app.setStyle(QStyleFactory.create(original_style))


@pytest.mark.parametrize("style", ["Fusion", "Windows"])
@pytest.mark.parametrize("font_size", [13, 18, 26])
def test_rename_has_room_for_the_full_font_height(rename_panel, style, font_size):
    _scene, panel, editor = rename_panel(style, font_size)
    assert editor is not None
    editor.setText("Layer gjÅÉ")
    option = QStyleOptionFrame()
    editor.initStyleOption(option)
    content = editor.style().subElementRect(
        QStyle.SubElement.SE_LineEditContents, option, editor)
    margins = editor.textMargins()
    assert content.height() - margins.top() - margins.bottom() >= (
        editor.fontMetrics().height() + 2
    ), "The rename field clips the font inside its frame and padding"
    row = panel.tree.visualItemRect(panel.tree.topLevelItem(0))
    assert row.top() <= editor.y()
    assert editor.geometry().bottom() <= row.bottom()


@pytest.mark.parametrize("key, expected", [
    (Qt.Key.Key_Return, "Layer gjÅÉ"),
    (Qt.Key.Key_Escape, "Default"),
])
def test_rename_still_commits_or_cancels(rename_panel, key, expected):
    scene, _panel, editor = rename_panel()
    editor.setText("Layer gjÅÉ")
    QTest.keyClick(editor, key)
    QApplication.processEvents()
    assert scene.layers.current.name == expected
