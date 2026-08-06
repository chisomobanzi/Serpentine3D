"""A detail you have stepped into is a window into the model, not a picture.

Two things stopped it being one. The construction plane inside a detail was
still the world plane, so a rectangle drawn in a front view had both corners on
one line of it and came out degenerate — nothing got made — and a circle came
out lying flat in world XY, edge-on to the view it was drawn in.

And a command that wants a point swallows double-clicks: the press picks a
point before the second click arrives, so you could not step into a detail once
a command was running, and the clicks you meant as a way in landed on the paper
as paper geometry.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.layout_view import detail_direction

FRAMES = {"top": {"x": 20.0, "y": 100.0, "w": 120.0, "h": 90.0},
          "front": {"x": 160.0, "y": 100.0, "w": 120.0, "h": 90.0}}


@pytest.fixture
def sheet():
    """A sheet with a top and a front detail looking at one box."""
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.add(g.make_box((-100.0, -80.0, 0.0), 200.0, 160.0, 60.0))
    lay = Layout(name="Sheet1")
    details = {}
    for view, frame in FRAMES.items():
        az, el = STANDARD_VIEWS[view]
        det = DetailView(azimuth=az, elevation=el, target=[0.0, 0.0, 30.0],
                         scale_denom=2.0, display_mode="wireframe", **frame)
        lay.details.append(det)
        details[view] = det
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    # The window is never shown, so nothing lays the panes out and the
    # pane keeps whatever size it was born with. Pixel distances are the
    # whole point of these tests, so say which size they are measured in.
    w.viewport.resize(640, 480)
    w.viewport.layout_view.fit()
    return w, lay, details


def _enter(w, detail):
    w.viewport.layout_view.entered_detail = detail.id


def _at(w, detail, fx: float, fy: float) -> QPointF:
    """Screen position at a fraction across a detail's frame."""
    lv = w.viewport.layout_view
    return QPointF(*lv.paper_to_screen(detail.x + detail.w * fx,
                                       detail.y + detail.h * fy))


def _press(w, pos: QPointF):
    w.viewport.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, pos, pos, Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def _draw(w, detail, command: str, *fracs):
    """Run `command`, clicking at fractions of `detail`'s frame."""
    w.processor.run(command)
    for fx, fy in fracs:
        _press(w, _at(w, detail, fx, fy))
    return list(w.scene.objects.values())


# ------------------------------------------------------------- which plane

def test_the_plane_inside_a_detail_is_the_one_it_looks_at(sheet):
    w, _lay, details = sheet
    det = details["front"]
    _enter(w, det)
    cp = w.ctx.cplane
    d, right, up = detail_direction(det)
    assert cp.origin == pytest.approx(det.target)
    assert cp.normal == pytest.approx(d)
    assert cp.xdir == pytest.approx(right)
    assert cp.ydir == pytest.approx(up)


def test_a_point_seen_through_a_detail_lies_on_that_plane(sheet):
    """Which is what makes the plane the right one: the picks it is given are
    already on it, so nothing is thrown away mapping them onto it."""
    w, _lay, details = sheet
    det = details["front"]
    _enter(w, det)
    vp = w.viewport
    vp.point_space = "model"
    pos = _at(w, det, 0.3, 0.7)
    pt = vp.world_point_at(pos.x(), pos.y())
    _u, _v, wdist = w.ctx.cplane.from_world(pt)
    assert wdist == pytest.approx(0.0, abs=1e-6)


def test_bare_paper_draws_on_the_plane_the_model_has(sheet):
    w, _lay, _details = sheet
    assert w.ctx.cplane is w.viewport.cplane


def test_the_model_space_plane_is_untouched(sheet):
    w, _lay, details = sheet
    _enter(w, details["front"])
    w.switch_space("model")
    assert w.ctx.cplane is w.viewport.cplane


# --------------------------------------------------- what gets made in there

def test_a_rectangle_in_a_front_detail_is_made_at_all(sheet):
    """The bug as reported: 'nothing gets made'. Both corners of a front-view
    rectangle sit on one line of the world plane."""
    w, lay, details = sheet
    det = details["front"]
    _enter(w, det)
    made = _draw(w, det, "rectangle", (0.25, 0.25), (0.75, 0.75))
    assert not w.processor.busy
    assert len(made) == 2, "the box, and the rectangle that was drawn"
    assert lay.objects == [], "and none of it on the paper"


def test_that_rectangle_stands_up_in_the_view_it_was_drawn_in(sheet):
    w, _lay, details = sheet
    det = details["front"]
    _enter(w, det)
    made = _draw(w, det, "rectangle", (0.25, 0.25), (0.75, 0.75))
    lo, hi = g.bbox(made[-1].shape)
    assert hi[1] - lo[1] == pytest.approx(0.0, abs=1e-6), "flat front-on"
    # half the frame across, at 1:2 — 120mm of paper is 240mm of model
    assert hi[0] - lo[0] == pytest.approx(120.0, abs=1.0)
    assert hi[2] - lo[2] == pytest.approx(90.0, abs=1.0)


def test_a_circle_in_a_front_detail_faces_the_view(sheet):
    """A world-XY circle drawn in a front view is a horizontal line — which
    also looks like nothing got made."""
    w, _lay, details = sheet
    det = details["front"]
    _enter(w, det)
    made = _draw(w, det, "circle", (0.5, 0.5), (0.75, 0.5))
    lo, hi = g.bbox(made[-1].shape)
    assert hi[1] - lo[1] == pytest.approx(0.0, abs=1e-6)
    assert hi[0] - lo[0] > 1.0
    assert hi[2] - lo[2] > 1.0


def test_a_rectangle_in_a_top_detail_still_lies_flat(sheet):
    """The named views are aimed 0.1 degrees off vertical so the camera basis
    never degenerates, and geometry must not inherit that lean."""
    w, _lay, details = sheet
    det = details["top"]
    _enter(w, det)
    made = _draw(w, det, "rectangle", (0.25, 0.25), (0.75, 0.75))
    lo, hi = g.bbox(made[-1].shape)
    assert lo[2] == pytest.approx(det.target[2], abs=1e-6)
    assert hi[2] == pytest.approx(det.target[2], abs=1e-6)


def test_a_point_in_a_top_detail_is_level_with_the_plane(sheet):
    """The lean is in the camera, and a pick is not a camera."""
    w, _lay, details = sheet
    det = details["top"]
    _enter(w, det)
    w.viewport.point_space = "model"
    # about the plane a free pick lands on, so nothing to be pulled off it by:
    # a corner of the box seen a few pixels away is not one of these two
    w.viewport.snaps.enabled = False
    for frac in ((0.1, 0.1), (0.9, 0.9)):
        pos = _at(w, det, *frac)
        pt = w.viewport.world_point_at(pos.x(), pos.y())
        assert pt[2] == pytest.approx(det.target[2], abs=1e-9)


def test_a_line_drawn_in_a_top_detail_comes_out_level(sheet):
    """A line is built from the picks themselves — nothing projects it onto a
    plane afterwards — so this is the pick that has to be level."""
    w, _lay, details = sheet
    det = details["top"]
    _enter(w, det)
    made = _draw(w, det, "line", (0.2, 0.2), (0.8, 0.8))
    lo, hi = g.bbox(made[-1].shape)
    assert hi[2] - lo[2] == pytest.approx(0.0, abs=1e-6), (
        "level to a micron across 120mm — the gap is the bounding box's own")


def test_a_top_detail_draws_on_the_world_axes(sheet):
    w, _lay, details = sheet
    _enter(w, details["top"])
    cp = w.ctx.cplane
    assert cp.normal == pytest.approx([0.0, 0.0, 1.0])
    assert abs(cp.xdir[2]) == pytest.approx(0.0, abs=1e-12)
    assert abs(cp.ydir[2]) == pytest.approx(0.0, abs=1e-12)


# ------------------------------------------------------------- the way in

def test_a_click_on_a_detail_steps_into_it_while_a_point_is_wanted(sheet):
    """A command that wants a point swallows double-clicks, so the click that
    lands on a detail is the way in."""
    w, _lay, details = sheet
    det = details["front"]
    w.processor.run("rectangle")
    _press(w, _at(w, det, 0.25, 0.25))
    assert w.viewport.layout_view.entered_detail == det.id


def test_the_click_that_steps_in_is_not_also_a_point(sheet):
    """Otherwise it is a paper point nobody meant, and two of them make the
    rectangle in paper space that was reported."""
    w, lay, details = sheet
    det = details["front"]
    w.processor.run("rectangle")
    _press(w, _at(w, det, 0.25, 0.25))
    assert w.processor.picked_points == []
    assert w.processor.busy
    assert lay.objects == []


def test_the_clicks_after_it_draw_through_the_detail(sheet):
    w, lay, details = sheet
    det = details["front"]
    w.processor.run("rectangle")
    for frac in ((0.25, 0.25), (0.25, 0.25), (0.75, 0.75)):
        _press(w, _at(w, det, *frac))
    assert not w.processor.busy
    assert len(w.scene.objects) == 2
    assert lay.objects == []


def test_a_click_in_the_detail_you_are_in_is_a_point(sheet):
    w, _lay, details = sheet
    det = details["front"]
    _enter(w, det)
    w.processor.run("rectangle")
    _press(w, _at(w, det, 0.25, 0.25))
    assert len(w.processor.picked_points) == 1


def test_a_click_on_another_detail_moves_the_window(sheet):
    w, _lay, details = sheet
    _enter(w, details["front"])
    w.processor.run("rectangle")
    _press(w, _at(w, details["top"], 0.5, 0.5))
    assert w.viewport.layout_view.entered_detail == details["top"].id
    assert w.processor.picked_points == []


def test_a_click_on_bare_paper_is_still_a_paper_point(sheet):
    w, _lay, _details = sheet
    lv = w.viewport.layout_view
    w.processor.run("rectangle")
    pos = QPointF(*lv.paper_to_screen(380.0, 40.0))
    _press(w, pos)
    assert lv.entered_detail is None
    assert len(w.processor.picked_points) == 1


def test_a_paper_command_never_steps_in(sheet):
    """`text` and its like want paper millimetres, and a detail is something
    they get written on top of."""
    w, _lay, details = sheet
    det = details["front"]
    w.processor.run("rectangle")
    w.viewport.point_space = "paper"        # as a paper command leaves it
    _press(w, _at(w, det, 0.25, 0.25))
    assert w.viewport.layout_view.entered_detail is None
    assert len(w.processor.picked_points) == 1


def test_stepping_in_says_so(sheet):
    """The click was taken and no point was placed, so something has to say
    what happened to it."""
    w, _lay, details = sheet
    said = []
    w.ctx.add_echo_listener(said.append)
    w.processor.run("rectangle")
    _press(w, _at(w, details["front"], 0.25, 0.25))
    assert any("detail" in s.lower() for s in said)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
