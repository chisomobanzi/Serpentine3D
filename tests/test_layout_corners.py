"""Picking the corners of a detail frame, and moving them by numbers.

From a request: "i also want to be able to select individual vertices on a
detail too, and for the move command to be able to work on them" — the
vertices being the four corners of the frame on paper. The gold grips could
always be dragged; now a corner can be *chosen*, and `move` puts it at typed
paper millimetres. Paper only: the model never moves.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter

from serpentine3d.api import SerpApi
from serpentine3d.app import MainWindow
from serpentine3d.core.layout import (
    DetailView,
    Layout,
    TextNote,
    detail_corners,
    nudge_detail_corners,
)

A = {"x": 10.0, "y": 10.0, "w": 150.0, "h": 100.0}
B = {"x": 200.0, "y": 150.0, "w": 150.0, "h": 100.0}


# ------------------------------------------------------- the paper maths

def test_the_corners_run_anticlockwise_from_the_bottom_left():
    """The index is what a picked corner is named by, so the order is part
    of the contract, not an implementation detail."""
    det = DetailView(**A)
    assert detail_corners(det) == ((10.0, 10.0), (160.0, 10.0),
                                  (160.0, 110.0), (10.0, 110.0))


def test_a_corner_takes_the_two_edges_that_meet_at_it():
    det = DetailView(**A)
    nudge_detail_corners(det, [0], 10.0, 5.0)
    assert (det.x, det.y) == pytest.approx((20.0, 15.0))
    assert (det.w, det.h) == pytest.approx((140.0, 95.0))


def test_the_far_corner_stretches_instead_of_shifting():
    det = DetailView(**A)
    nudge_detail_corners(det, [2], 10.0, 5.0)
    assert (det.x, det.y) == pytest.approx((10.0, 10.0))
    assert (det.w, det.h) == pytest.approx((160.0, 105.0))


def test_two_corners_move_the_edge_between_them():
    det = DetailView(**A)
    nudge_detail_corners(det, [0, 1], 0.0, 10.0)      # the bottom edge
    assert (det.x, det.w) == pytest.approx((10.0, 150.0))
    assert (det.y, det.h) == pytest.approx((20.0, 90.0))


def test_all_four_corners_move_the_whole_detail():
    det = DetailView(**A)
    nudge_detail_corners(det, [0, 1, 2, 3], 12.0, -4.0)
    assert (det.x, det.y) == pytest.approx((22.0, 6.0))
    assert (det.w, det.h) == pytest.approx((150.0, 100.0))


def test_a_frame_cannot_be_pinched_away_to_nothing():
    det = DetailView(**A)
    nudge_detail_corners(det, [1], -148.0, 0.0)
    assert det.w == pytest.approx(5.0)


# ------------------------------------------------------------- the fixture

@pytest.fixture
def sheet():
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


def _pick_detail(lv, det):
    """Click the middle of a detail, which is how its grips appear."""
    _press(lv, det.x + det.w / 2, det.y + det.h / 2)
    lv.release_drag()


def _grip(lv, det, i, add=False):
    """Press and let go on corner i — a choice, not a drag."""
    gx, gy = detail_corners(det)[i]
    _press(lv, gx, gy, add=add)
    lv.release_drag()


# -------------------------------------------------------------- picking

def test_clicking_a_grip_picks_that_corner(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    assert lv.corners == [(det, 0)]


def test_choosing_a_corner_does_not_resize_the_detail(sheet):
    """Pressing a grip used to mean only one thing: start resizing."""
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 2)
    assert (det.w, det.h) == pytest.approx((A["w"], A["h"]))


def test_dragging_a_grip_still_resizes(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _press(lv, det.x, det.y)
    _drag_to(lv, det.x - 10, det.y - 10)
    lv.release_drag()
    assert (det.x, det.y) == pytest.approx((0.0, 0.0))
    assert (det.w, det.h) == pytest.approx((160.0, 110.0))


def test_shift_clicking_a_second_grip_adds_it(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _grip(lv, det, 1, add=True)
    assert lv.corners == [(det, 0), (det, 1)]


def test_shift_clicking_a_picked_corner_takes_it_back_out(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _grip(lv, det, 1, add=True)
    _grip(lv, det, 0, add=True)
    assert lv.corners == [(det, 1)]


def test_dragging_one_of_two_picked_corners_moves_the_edge(sheet):
    """Two corners of an edge, dragged, is how you move an edge."""
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _grip(lv, det, 1, add=True)
    _press(lv, det.x, det.y)
    _drag_to(lv, det.x, det.y + 10)
    lv.release_drag()
    assert (det.x, det.w) == pytest.approx((A["x"], A["w"]))
    assert (det.y, det.h) == pytest.approx((20.0, 90.0))


def test_clicking_the_body_lets_go_of_the_corner(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _pick_detail(lv, det)
    assert lv.corners == []


def test_picking_another_detail_lets_go_of_the_corner(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _pick_detail(lv, lay.details[1])
    assert lv.corners == []


def test_a_corner_does_not_outlive_a_lone_selection(sheet):
    """Grips belong to one detail; add a second and there are none to own
    the corner any more."""
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _press(lv, 275, 200, add=True)
    lv.release_drag()
    lv._prune()
    assert lv.corners == []


def test_a_stale_corner_is_dropped(sheet):
    """Undo replaces the sheet, so whatever was picked is gone with it."""
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    lay.details.pop(0)
    lv._prune()
    assert lv.corners == []


def test_a_corner_of_a_locked_detail_is_pickable_but_does_not_move(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    det.locked = True
    _pick_detail(lv, det)
    _press(lv, det.x, det.y)
    _drag_to(lv, det.x - 20, det.y - 20)
    lv.release_drag()
    assert lv.corners == [(det, 0)]
    assert (det.x, det.w) == pytest.approx((A["x"], A["w"]))


def test_escape_lets_go_of_the_corner_before_the_detail(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)

    def esc():
        w.viewport.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier))

    esc()
    assert lv.corners == []
    assert lv.selected == [("detail", det)], "the detail is still picked"
    esc()
    assert lv.selected == []


def test_the_status_bar_says_a_corner_is_what_is_picked(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    w._update_status()
    assert "1 corner selected" in w.statusBar().currentMessage()


def test_the_corner_count_does_not_eat_the_object_count(sheet):
    """Both numbers share the one status line, and the scene is empty."""
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    _grip(lv, det, 1, add=True)
    w._update_status()
    assert "0 object(s)" in w.statusBar().currentMessage()
    assert "2 corners selected" in w.statusBar().currentMessage()


# ------------------------------------------------------------- on screen

def _drawn(lv, paint) -> QImage:
    img = QImage(lv.vp.width(), lv.vp.height(), QImage.Format.Format_RGB32)
    img.fill(Qt.GlobalColor.black)
    painter = QPainter(img)
    paint(painter)
    painter.end()
    return img


def test_a_picked_corner_looks_different_from_the_other_three(sheet):
    _, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    plain = _drawn(lv, lv._paint_selection)
    _grip(lv, det, 0)
    picked = _drawn(lv, lv._paint_selection)
    at = [tuple(int(c) for c in lv.paper_to_screen(gx, gy))
          for gx, gy in detail_corners(det)]
    x, y = at[0]
    assert picked.pixelColor(x, y) != plain.pixelColor(x, y), \
        "the chosen corner is drawn the same as an unchosen one"
    for x, y in at[1:]:
        assert picked.pixelColor(x, y) == plain.pixelColor(x, y), \
            "an unchosen corner changed too"


# -------------------------------------------------------------- the move

def test_move_puts_a_picked_corner_at_typed_millimetres(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    SerpApi(w).command("move", inputs=["10,10,0", "20,15,0"])
    assert (det.x, det.y) == pytest.approx((20.0, 15.0))
    assert (det.w, det.h) == pytest.approx((140.0, 95.0))


def test_move_takes_every_picked_corner(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 1)
    _grip(lv, det, 2, add=True)
    SerpApi(w).command("move", inputs=["160,10,0", "180,10,0"])
    assert (det.x, det.w) == pytest.approx((10.0, 170.0))
    assert (det.y, det.h) == pytest.approx((10.0, 100.0))


def test_move_with_no_corner_picked_moves_the_whole_detail(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    SerpApi(w).command("move", inputs=["0,0,0", "10,20,0"])
    assert (det.x, det.y) == pytest.approx((20.0, 30.0))
    assert (det.w, det.h) == pytest.approx((A["w"], A["h"]))


def test_move_carries_annotations_off_the_same_pick(sheet):
    w, lv, lay = sheet
    note = TextNote(x=30.0, y=200.0, text="hi", height=4.0)
    lay.notes.append(note)
    _press(lv, 30.5, 200.5)
    lv.release_drag()
    assert lv.selected == [("note", note)]
    SerpApi(w).command("move", inputs=["0,0,0", "5,0,0"])
    assert note.x == pytest.approx(35.0)


def test_move_on_a_sheet_with_nothing_picked_says_so(sheet):
    w, _, lay = sheet
    out = SerpApi(w).command("move", inputs=[])
    assert any("picked" in m for m in out["messages"]), out["messages"]
    assert lay.details[0].x == pytest.approx(A["x"])


def test_move_on_a_sheet_leaves_the_model_alone(sheet):
    w, lv, lay = sheet
    api = SerpApi(w)
    # the box has to be built in the model; bare paper has no model point to
    # build it from, and says so rather than guessing (test_layout_space.py)
    w.viewport.space = "model"
    api.command("box", inputs=["0,0,0", "40,40,0", "30"])
    w.viewport.space = lay.id
    obj = w.scene.all()[0]
    before = obj.shape
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    api.command("move", inputs=["10,10,0", "30,30,0"])
    assert w.scene.all()[0].shape is before, "the model moved"
    assert det.x == pytest.approx(30.0)


def test_undo_puts_the_corner_back(sheet):
    w, lv, lay = sheet
    det = lay.details[0]
    _pick_detail(lv, det)
    _grip(lv, det, 0)
    SerpApi(w).command("move", inputs=["10,10,0", "20,15,0"])
    w.history.undo()
    back = w.scene.layouts[0].details[0]
    assert (back.x, back.y) == pytest.approx((A["x"], A["y"]))
    assert (back.w, back.h) == pytest.approx((A["w"], A["h"]))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
