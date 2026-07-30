"""Zooming while a sheet is showing.

Every zoom command drove the model camera, which on a sheet is the one thing
you cannot see. `zoom Extents` on bare paper quietly re-aimed it and left the
page exactly as it was; `zoom Window` was refused outright, because a window
wants two points and bare paper has no model point to give. Inside a detail
both moved the camera rather than the detail.

The rule is the one the wheel already followed: on bare paper a zoom is about
the page, inside a detail it is about the detail, and only in the model window
is it about the camera.
"""

from __future__ import annotations

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import resolve
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, PaperObject, TextNote

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [20.0, 20.0, 20.0]}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((0.0, 0.0, 0.0), 40.0, 40.0, 40.0))
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    lay.objects.append(PaperObject(
        shape=g.make_line((10.0, 10.0, 0.0), (90.0, 10.0, 0.0)), name="Rule"))
    lay.notes.append(TextNote(x=50.0, y=200.0, text="SECTION A-A"))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = None
    said: list = []
    w.ctx.add_echo_listener(said.append)
    return w, lv, lay, box, said


def _run(w, cmd, *texts):
    w.run_command(cmd)
    for t in texts:
        w.processor.provide_text(t)


def _view(lv):
    return lv.vp.width(), lv.vp.height()


def _covers(lv, x0, y0, x1, y1) -> bool:
    """Is that paper rectangle framed — on screen, and filling it?"""
    vw, vh = _view(lv)
    ax, ay = lv.paper_to_screen(x0, y0)
    bx, by = lv.paper_to_screen(x1, y1)
    lo_x, hi_x = min(ax, bx), max(ax, bx)
    lo_y, hi_y = min(ay, by), max(ay, by)
    if lo_x < -0.5 or lo_y < -0.5 or hi_x > vw + 0.5 or hi_y > vh + 0.5:
        return False
    return (hi_x - lo_x) >= 0.9 * vw or (hi_y - lo_y) >= 0.9 * vh


# -- on bare paper -------------------------------------------------------------

def test_zoom_window_is_not_refused_on_bare_paper(sheet):
    """It was: a window wants two points, and the guard that keeps model
    coordinates off the page turned it away before it could ask."""
    w, _lv, _lay, _box, said = sheet
    _run(w, "zoom", "Window", "60,40,0", "160,120,0")
    assert not w.processor.busy
    assert not any("not the model" in m for m in said)


def test_zoom_window_frames_that_piece_of_paper(sheet):
    w, lv, _lay, _box, _said = sheet
    before = lv.px_per_mm
    _run(w, "zoom", "Window", "60,40,0", "160,120,0")
    vw, vh = _view(lv)
    assert lv.screen_to_paper(vw / 2, vh / 2) == pytest.approx(
        (110.0, 80.0), abs=1e-6)
    assert lv.px_per_mm > before
    assert _covers(lv, 60.0, 40.0, 160.0, 120.0)


def test_zoomwindow_on_its_own_does_the_same(sheet):
    w, lv, _lay, _box, _said = sheet
    _run(w, "zoomwindow", "60,40,0", "160,120,0")
    assert _covers(lv, 60.0, 40.0, 160.0, 120.0)


def test_zooming_the_page_leaves_the_model_camera_alone(sheet):
    w, _lv, _lay, _box, _said = sheet
    before = w.viewport.camera.distance
    _run(w, "zoom", "Window", "60,40,0", "160,120,0")
    _run(w, "zoomextents")
    assert w.viewport.camera.distance == pytest.approx(before)


def test_zoom_extents_puts_the_whole_page_back_on_screen(sheet):
    w, lv, lay, _box, _said = sheet
    _run(w, "zoom", "Window", "60,40,0", "70,50,0")
    _run(w, "zoomextents")
    assert _covers(lv, 0.0, 0.0, lay.paper_w, lay.paper_h)


def test_extents_reaches_something_dropped_off_the_page(sheet):
    """Extents means everything, and a border nudged off the sheet is the
    one thing you most need a way back to."""
    w, lv, lay, _box, _said = sheet
    lay.objects.append(PaperObject(
        shape=g.make_line((500.0, 400.0, 0.0), (560.0, 440.0, 0.0)),
        name="Stray"))
    _run(w, "zoomextents")
    sx, sy = lv.paper_to_screen(560.0, 440.0)
    vw, vh = _view(lv)
    assert -0.5 <= sx <= vw + 0.5
    assert -0.5 <= sy <= vh + 0.5


def test_zoom_selected_frames_the_picked_frame(sheet):
    w, lv, lay, _box, _said = sheet
    lv.selected = [("detail", lay.details[0])]
    _run(w, "zoom", "Selected")
    d = lay.details[0]
    assert _covers(lv, d.x, d.y, d.x + d.w, d.y + d.h)


def test_zoom_selected_with_nothing_picked_falls_back_to_the_page(sheet):
    w, lv, lay, _box, said = sheet
    _run(w, "zoom", "Window", "60,40,0", "70,50,0")
    _run(w, "zoom", "Selected")
    assert _covers(lv, 0.0, 0.0, lay.paper_w, lay.paper_h)
    assert "nothing selected" in said[-1].lower()


def test_zoom_in_and_out_work_on_the_page(sheet):
    w, lv, _lay, _box, _said = sheet
    start = lv.px_per_mm
    _run(w, "zoom", "In")
    closer = lv.px_per_mm
    assert closer > start
    _run(w, "zoom", "Out")
    assert lv.px_per_mm < closer


# -- inside a detail -----------------------------------------------------------

def test_zoom_window_in_a_detail_zooms_the_detail(sheet):
    """The points are model points there, as every point in a detail is."""
    w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    before = det.scale_denom
    _run(w, "zoomwindow", "0,0,0", "20,20,0")
    assert det.scale_denom < before
    assert det.target == pytest.approx([10.0, 10.0, 20.0], abs=1e-6)


def test_zoom_window_in_a_detail_leaves_the_camera_alone(sheet):
    w, lv, lay, _box, _said = sheet
    lv.entered_detail = lay.details[0].id
    before = w.viewport.camera.distance
    _run(w, "zoomwindow", "0,0,0", "20,20,0")
    assert w.viewport.camera.distance == pytest.approx(before)


def test_what_the_window_asked_for_fills_the_frame(sheet):
    w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    _run(w, "zoomwindow", "0,0,0", "20,20,0")
    from serpentine3d.core.layout import detail_project
    ax, ay = detail_project(det, (0.0, 0.0, 20.0))
    bx, by = detail_project(det, (20.0, 20.0, 20.0))
    assert min(ax, bx) >= det.x - 1e-6
    assert max(ax, bx) <= det.x + det.w + 1e-6
    assert min(ay, by) >= det.y - 1e-6
    assert max(ay, by) <= det.y + det.h + 1e-6
    assert max(abs(bx - ax) / det.w, abs(by - ay) / det.h) > 0.9


def test_zoom_extents_in_a_detail_fits_the_model_in_the_frame(sheet):
    w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    det.scale_denom = 0.2                # far too close to see the box
    _run(w, "zoomextents")
    from serpentine3d.core.layout import detail_project
    for corner in ((0.0, 0.0, 0.0), (40.0, 40.0, 40.0)):
        px, py = detail_project(det, corner)
        assert det.x - 1e-6 <= px <= det.x + det.w + 1e-6
        assert det.y - 1e-6 <= py <= det.y + det.h + 1e-6


def test_a_locked_detail_is_not_re_aimed_by_a_zoom(sheet):
    """The lock is what stops the wheel moving it, and a typed zoom is the
    same act by another route."""
    w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    det.locked = True
    lv.entered_detail = det.id
    _run(w, "zoomwindow", "0,0,0", "20,20,0")
    assert det.scale_denom == DET["scale_denom"]
    assert det.target == DET["target"]


def test_zoom_in_a_detail_changes_its_scale_not_the_page(sheet):
    w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    lv.entered_detail = det.id
    ppm, scale = lv.px_per_mm, det.scale_denom
    _run(w, "zoom", "In")
    assert det.scale_denom < scale
    assert lv.px_per_mm == pytest.approx(ppm)


# -- and the first look at a sheet still belongs to the paint ------------------

class _FakeVp:
    """Enough of a viewport for the paper transform, at a settled size."""

    def __init__(self, scene, lay):
        self.scene = scene
        self.space = lay.id

    def width(self):
        return 1000

    def height(self):
        return 700

    def update(self):
        pass

    def isVisible(self):
        return True


def test_a_zoom_on_screen_is_not_fitted_over(sheet):
    """The paint fits a sheet the first time it shows one. It has to stop
    doing that once the view has been aimed, or a zoom typed before the
    first frame would be thrown away by it."""
    from serpentine3d.ui.layout_view import LayoutView
    w, _lv, lay, _box, _said = sheet
    lv = LayoutView(_FakeVp(w.scene, lay))
    lv.zoom_paper(0.0, 0.0, 100.0, 100.0)
    assert lv._fitted_for == lay.id


def test_a_view_not_on_screen_yet_leaves_the_first_fit_alone(sheet):
    """An extra pane opened onto a sheet zooms before the window has decided
    how big it is, so the size it would fit for is not the size it gets."""
    from serpentine3d.ui.viewport import Viewport
    w, _lv, lay, _box, _said = sheet
    vp = Viewport(w.scene, w.selection, w.cfg)
    vp.set_space(lay.id)
    vp.zoom_extents()
    assert vp.layout_view._fitted_for is None


# -- and the model window is untouched -----------------------------------------

def test_the_model_window_still_zooms_its_camera(sheet):
    w, _lv, _lay, _box, _said = sheet
    w.viewport.set_space("model")
    before = w.viewport.camera.distance
    _run(w, "zoomwindow", "0,0,0", "10,10,0")
    assert w.viewport.camera.distance != pytest.approx(before)


@pytest.mark.parametrize("name", ["zoom", "zoomwindow", "zoomextents",
                                  "zoomselected"])
def test_the_zoom_commands_are_allowed_on_a_sheet(name):
    assert resolve(name).space == "any"
