"""Enter in a Properties field commits the field and nothing more.

Seen in the live app: with an object picked, typing a new name into the
Properties panel's Name field and pressing Enter renamed the object — and
then started the last command again, the command line showing `> circle` and
its first prompt. Enter in a field means "take what I typed"; it is not the
empty-prompt Enter that Rhino users hit to repeat a command. That repeat has
to stay for the viewport and the command line, and stay out of the panel.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


def _window():
    w = MainWindow()
    w.resize(1200, 800)
    QApplication.processEvents()
    return w


def _ran_and_gave_up(w, name: str):
    """Set-up only: a command run and cancelled, so there is one to repeat."""
    w.processor.run(name)
    assert w.processor.busy and w.processor.active.name == name
    w.processor.cancel()
    assert not w.processor.busy
    assert w.processor.last_command == name


def _enter(field, text: str):
    """Type into a field and press Enter, as a user would."""
    field.setFocus()
    field.clear()
    QTest.keyClicks(field, text)
    QTest.keyClick(field, Qt.Key.Key_Return)
    QApplication.processEvents()


def _no_command_started(w):
    assert not w.processor.busy, \
        f"Enter in the field started `{w.processor.active.name}` again"
    assert w.processor.active is None


def _pick_on_sheet(w, kind: str, thing):
    """Select on the sheet the way a click does, panel and all."""
    lv = w.viewport.layout_view
    lv.selected = [(kind, thing)]
    w.viewport.layoutSelectionChanged.emit()


def _scale_combo(panel) -> QComboBox | None:
    for combo in panel.findChildren(QComboBox):
        items = [combo.itemText(i) for i in range(combo.count())]
        if "1:50" in items and "1:100" in items:
            return combo
    return None


# ------------------------------------------------------------ the name field

def test_renaming_with_enter_does_not_repeat_the_last_command():
    w = _window()
    _ran_and_gave_up(w, "circle")
    box = w.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    w.selection.set([box.id])
    assert w.properties.name_edit.isEnabled()

    _enter(w.properties.name_edit, "Plinth")

    assert w.scene.get(box.id).name == "Plinth", "the rename itself must still happen"
    _no_command_started(w)


# ----------------------------------------------------------- the scale combo

def test_typing_a_detail_scale_with_enter_does_not_repeat_the_last_command():
    w = _window()
    _ran_and_gave_up(w, "line")
    lay = Layout(name="Sheet1")
    det = DetailView(**DET)
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    _pick_on_sheet(w, "detail", det)
    combo = _scale_combo(w.properties)
    assert combo is not None and combo.lineEdit() is not None

    _enter(combo.lineEdit(), "1:75")

    assert det.scale_denom == pytest.approx(75.0), "the rescale itself must still happen"
    _no_command_started(w)


# ------------------------------------------------------- the lineweight box

def test_typing_a_lineweight_with_enter_does_not_repeat_the_last_command():
    w = _window()
    _ran_and_gave_up(w, "line")
    lay = Layout(name="Sheet1")
    border = lay.add(g.make_rectangle((20.0, 20.0, 0.0), (120.0, 80.0, 0.0)),
                     name="Border")
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    _pick_on_sheet(w, "object", border)
    assert w.properties.lineweight_edit.isEnabled()

    _enter(w.properties.lineweight_edit, "0.7")

    assert border.lineweight == pytest.approx(0.7), "the change itself must still happen"
    _no_command_started(w)


# ---------------------------------------------------------------- the guard

def test_enter_on_an_empty_command_line_still_repeats_the_last_command():
    """The repeat is the right thing where nothing else wants the Enter."""
    w = _window()
    _ran_and_gave_up(w, "line")
    w.command_line.focus()
    QTest.keyClick(w.command_line.input, Qt.Key.Key_Return)
    assert w.processor.busy and w.processor.active.name == "line"


def test_enter_in_the_viewport_still_repeats_the_last_command():
    w = _window()
    _ran_and_gave_up(w, "circle")
    w.viewport.setFocus()
    QTest.keyClick(w.viewport, Qt.Key.Key_Return)
    assert w.processor.busy and w.processor.active.name == "circle"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
