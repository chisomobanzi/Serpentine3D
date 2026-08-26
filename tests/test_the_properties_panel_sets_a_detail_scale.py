"""The scale of a detail is set from the Properties panel, not just by command.

An architect reported: "In Layouts, the Detail scale should be easily set in
the Detail Properties panel." The only way was the `detailscale` command, which
means knowing the command exists and typing the scale blind. Pick a detail on
a sheet and the panel should say what scale it is at, offer the scales an
architect actually draws at, and let an odd one be typed in.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import DetailView, Layout

PRESETS = ["1:1", "1:2", "1:5", "1:10", "1:20", "1:50", "1:100", "1:200"]

FIRST = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
         "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}
SECOND = {"x": 200.0, "y": 30.0, "w": 160.0, "h": 120.0,
          "scale_denom": 5.0, "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def sheet():
    """A window showing a sheet with two details at different scales."""
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**FIRST))
    lay.details.append(DetailView(**SECOND))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    return w, w.properties, lay


def _pick(w, *details):
    """Select details the way a click does, panel and all."""
    lv = w.viewport.layout_view
    lv.selected = [("detail", d) for d in details]
    w.viewport.layoutSelectionChanged.emit()


def _items(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _scale_combo(panel) -> QComboBox | None:
    """The scale control, found by what it offers rather than how it is named."""
    for combo in panel.findChildren(QComboBox):
        if "1:50" in _items(combo) and "1:100" in _items(combo):
            return combo
    return None


def _type(combo: QComboBox, text: str):
    """Type a scale into the control and press Enter, as a user would."""
    edit = combo.lineEdit()
    assert edit is not None, "the scale control is not editable"
    edit.clear()
    QTest.keyClicks(edit, text)
    QTest.keyClick(edit, Qt.Key.Key_Return)


# ------------------------------------------------------------- what it shows

def test_picking_a_detail_shows_its_scale(sheet):
    """The report as it was met: pick a detail and there is nowhere in the
    panel that says, or sets, what scale it is at."""
    w, panel, lay = sheet
    det = lay.details[0]
    _pick(w, det)
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    assert combo.currentText() == det.scale_text() == "1:2"


def test_the_scales_an_architect_draws_at_are_on_offer_in_order(sheet):
    w, panel, lay = sheet
    _pick(w, lay.details[0])
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    assert [t for t in _items(combo) if t in PRESETS] == PRESETS


def test_an_odd_scale_can_be_typed(sheet):
    w, panel, lay = sheet
    _pick(w, lay.details[0])
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    assert combo.isEditable()


# --------------------------------------------------------------- editing it

def test_choosing_a_preset_rescales_the_detail(sheet):
    w, panel, lay = sheet
    det = lay.details[0]
    _pick(w, det)
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    combo.setCurrentText("1:100")
    assert det.scale_denom == pytest.approx(100.0)
    assert det.scale_text() == "1:100"


def test_typing_a_scale_rescales_the_detail(sheet):
    w, panel, lay = sheet
    det = lay.details[0]
    _pick(w, det)
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    _type(combo, "1:75")
    assert det.scale_denom == pytest.approx(75.0)
    assert det.scale_text() == "1:75"


def test_a_scale_that_is_not_one_is_refused(sheet):
    """What `detailscale` would not take, the panel does not take either, and
    the control goes back to saying what the scale really is."""
    w, panel, lay = sheet
    det = lay.details[0]
    _pick(w, det)
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    for junk in ("banana", "0"):
        _type(combo, junk)
        assert det.scale_denom == pytest.approx(2.0)
        assert combo.currentText() == "1:2"


def test_rescaling_is_one_undo(sheet):
    w, panel, lay = sheet
    _pick(w, lay.details[0])
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    combo.setCurrentText("1:100")
    w.history.undo()
    back = w.scene.layouts[0].details[0]
    assert back.scale_denom == pytest.approx(2.0)
    assert back.scale_text() == "1:2"


# ------------------------------------------------------- moving between them

def test_picking_another_detail_shows_that_ones_scale(sheet):
    """Not the last one's: a stale "1:2" over a 1:5 detail is exactly the
    wrong number to be editing from."""
    w, panel, lay = sheet
    first, second = lay.details
    _pick(w, first)
    combo = _scale_combo(panel)
    assert combo is not None, "no scale control on the panel for a detail"
    assert combo.currentText() == "1:2"
    _pick(w, second)
    assert combo.currentText() == second.scale_text() == "1:5"
    assert first.scale_denom == pytest.approx(2.0), "and nothing was changed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
