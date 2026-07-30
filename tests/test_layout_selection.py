"""Picking things on the layout sheet.

From a bug report: "selection doesn't seem to work on the layout screen? i
cant drag select, or directly click a detail window". Clicking did select one
thing, but nothing else in the app agreed it had — and there was no rubber
band on paper at all, because the layout branch of `mousePressEvent` returns
before the model-space band is ever set up.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent, QPainter

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import DetailView, Layout, TextNote

# Two details, far enough apart that a box can take one and leave the other.
A = {"x": 10.0, "y": 10.0, "w": 150.0, "h": 100.0}
B = {"x": 200.0, "y": 150.0, "w": 150.0, "h": 100.0}


@pytest.fixture
def sheet():
    """A window looking at a sheet with two details on it."""
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**A))
    lay.details.append(DetailView(**B))
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, lay


def _press(lv, px, py, add=False):
    lv.press(*lv.paper_to_screen(px, py), add=add)


def _drag_to(lv, px, py):
    lv.drag_selected(*lv.paper_to_screen(px, py))


def _box(lv, x0, y0, x1, y1, add=False):
    """Press on empty paper, drag, release — a rubber band in paper coords."""
    _press(lv, x0, y0, add=add)
    _drag_to(lv, x1, y1)
    lv.release_drag()


def _kinds(lv):
    return sorted(k for k, _ in lv.selected)


# ------------------------------------------------------------- clicking

def test_clicking_a_detail_selects_just_it(sheet):
    _, lv, lay = sheet
    _press(lv, 85, 60)
    assert lv.selected == [("detail", lay.details[0])]


def test_clicking_empty_paper_clears_the_selection(sheet):
    _, lv, _ = sheet
    _press(lv, 85, 60)
    _press(lv, 400, 280)
    lv.release_drag()
    assert lv.selected == []


def test_shift_click_adds_a_second_detail(sheet):
    _, lv, lay = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    assert lv.selected == [("detail", lay.details[0]),
                           ("detail", lay.details[1])]


def test_shift_clicking_a_selected_detail_takes_it_back_out(sheet):
    _, lv, lay = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    _press(lv, 85, 60, add=True)
    assert lv.selected == [("detail", lay.details[1])]


def test_clicking_one_of_several_selected_details_keeps_the_others(sheet):
    """Otherwise you could never drag a group: the press would throw away
    everything but the one under the cursor."""
    _, lv, _ = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    _press(lv, 275, 200)
    assert len(lv.selected) == 2


def test_clicking_a_selected_detail_without_dragging_narrows_to_it(sheet):
    """The press keeps the group so the group can be dragged. Letting go
    without having moved means you were choosing, not dragging."""
    _, lv, lay = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    _press(lv, 275, 200)
    lv.release_drag()
    assert lv.selected == [("detail", lay.details[1])]


# ----------------------------------------------------------- drag select

def test_dragging_a_box_across_the_paper_picks_up_the_details_it_covers(sheet):
    _, lv, lay = sheet
    _box(lv, 5, 5, 360, 260)
    assert lv.selected == [("detail", lay.details[0]),
                           ("detail", lay.details[1])]


def test_the_band_is_live_while_you_drag(sheet):
    _, lv, _ = sheet
    _press(lv, 5, 5)
    _drag_to(lv, 200, 150)
    assert lv.box is not None
    lv.release_drag()
    assert lv.box is None, "the band must not outlive the drag"


def test_a_box_that_only_clips_a_detail_leaves_it_alone(sheet):
    """Left to right is a window: it takes what it wholly encloses."""
    _, lv, _ = sheet
    _box(lv, 5, 5, 100, 60)
    assert lv.selected == []


def test_dragging_right_to_left_takes_anything_it_touches(sheet):
    """Right to left is a crossing, same as in model space."""
    _, lv, lay = sheet
    _box(lv, 170, 5, 100, 60)
    assert lv.selected == [("detail", lay.details[0])]


def test_a_click_that_does_not_travel_is_not_a_box(sheet):
    _, lv, _ = sheet
    _press(lv, 400, 280)
    lv.release_drag()
    assert lv.selected == []
    assert lv.box is None


def test_a_box_picks_up_annotations_too(sheet):
    _, lv, lay = sheet
    lay.notes.append(TextNote(x=30.0, y=200.0, text="hi", height=4.0))
    _box(lv, 20, 190, 120, 240)
    assert _kinds(lv) == ["note"]


def test_shift_dragging_a_box_adds_to_what_is_already_picked(sheet):
    _, lv, _ = sheet
    _press(lv, 275, 200)
    _box(lv, 5, 5, 170, 120, add=True)
    assert len(lv.selected) == 2


def test_a_box_does_not_start_inside_a_detail_you_have_entered(sheet):
    """Inside a detail the sheet is not what you are pointing at."""
    _, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    _press(lv, 85, 60)
    assert lv.box is None


# --------------------------------------------------- what selection is for

def test_dragging_a_multiple_selection_moves_every_detail(sheet):
    _, lv, lay = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    _press(lv, 275, 200)                    # start the drag on one of them
    _drag_to(lv, 285, 210)
    lv.release_drag()
    assert lay.details[0].x == pytest.approx(20.0)
    assert lay.details[1].x == pytest.approx(210.0)


def test_delete_removes_every_selected_detail(sheet):
    _, lv, lay = sheet
    _box(lv, 5, 5, 360, 260)
    assert lv.delete_selected()
    assert lay.details == []
    assert lv.selected == []


def test_a_locked_detail_is_selectable_but_does_not_move(sheet):
    _, lv, lay = sheet
    lay.details[0].locked = True
    _press(lv, 85, 60)
    _drag_to(lv, 120, 90)
    lv.release_drag()
    assert lv.selected == [("detail", lay.details[0])]
    assert lay.details[0].x == pytest.approx(A["x"])


def test_the_status_bar_counts_what_is_picked_on_the_sheet(sheet):
    """The report said selection "doesn't work"; a readout stuck on 0
    selected is most of why it looks that way."""
    w, lv, _ = sheet
    _box(lv, 5, 5, 360, 260)
    w._update_status()
    assert "2 selected" in w.statusBar().currentMessage()


def test_escape_clears_the_sheet_selection(sheet):
    w, lv, _ = sheet
    _press(lv, 85, 60)
    w.viewport.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier))
    assert lv.selected == []


def test_resize_grips_only_grab_when_one_detail_is_picked(sheet):
    """Dragging a corner of one of five details would have to mean something
    for the other four, and it does not."""
    _, lv, lay = sheet
    _press(lv, 85, 60)
    _press(lv, 275, 200, add=True)
    _press(lv, A["x"], A["y"])              # the bottom-left grip of A
    _drag_to(lv, A["x"] - 20, A["y"] - 20)
    lv.release_drag()
    assert lay.details[0].w == pytest.approx(A["w"]), "it resized instead"


def test_a_stale_selection_is_dropped(sheet):
    """Undo can take the sheet out from under whatever was picked."""
    _, lv, lay = sheet
    _press(lv, 85, 60)
    lay.details.pop(0)
    lv._prune()
    assert lv.selected == []


# ------------------------------------------------------------- on screen

def _drawn(lv, paint) -> QImage:
    img = QImage(lv.vp.width(), lv.vp.height(), QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    paint(painter)
    painter.end()
    return img


def _lit_near(img, x, y, r=6) -> bool:
    """Anything drawn over the black fill within r pixels of (x, y)."""
    for sy in range(max(0, int(y) - r), min(img.height(), int(y) + r)):
        for sx in range(max(0, int(x) - r), min(img.width(), int(x) + r)):
            if img.pixelColor(sx, sy) != Qt.GlobalColor.black:
                return True
    return False


def test_every_picked_detail_is_framed(sheet):
    _, lv, lay = sheet
    _box(lv, 5, 5, 360, 260)
    img = _drawn(lv, lv._paint_selection)
    for det in lay.details:
        x, y = lv.paper_to_screen(det.x, det.y)
        assert _lit_near(img, x, y), f"no frame on {det.id}"


def test_the_band_is_on_screen_while_you_drag(sheet):
    _, lv, _ = sheet
    _press(lv, 5, 5)
    _drag_to(lv, 200, 150)
    img = _drawn(lv, lv._paint_box)
    mx, my = lv.paper_to_screen(100, 5)      # midpoint of the bottom edge
    assert _lit_near(img, mx, my)


def test_the_viewport_starts_a_band_on_a_left_press_over_empty_paper(sheet):
    """The whole chain: the layout branch of mousePressEvent used to return
    before any of this existed."""
    w, lv, _ = sheet
    vp = w.viewport
    at = QPointF(*lv.paper_to_screen(400.0, 280.0))
    vp.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, at, at, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    to = QPointF(*lv.paper_to_screen(5.0, 5.0))
    vp.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, to, to, Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert lv.box is not None
    vp.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, to, to, Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert len(lv.selected) == 2, "a crossing over the whole sheet"
    assert lv.box is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
