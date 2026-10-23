"""A clipping plane cuts the model in a detail as it does in a model view (#94).

A detail is a window onto the model, so a section made with a clipping
plane is what you want to put on the sheet. But a detail is drawn while
the pane is showing the sheet, and the planes were only handed to the
shader in model space, so every detail showed the model whole. A detail
drawn in 3D (wireframe, shaded, ghosted) now takes the same cut, on screen
and in the PDF, and a shaded one closes what it cuts with the same caps.
A hidden-line detail, which is what `detail` places, takes it too: see
the end of this file.

A cap measured itself against the pane, which a detail is not: its cut
line was widened for the pane's size and its hatch spaced by the pane's
camera. In a detail the line is measured against the detail, and the
hatch falls at its spacing on the sheet, the way a hidden-line detail
hatches its cut.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui.camera import STANDARD_VIEWS

PX_W, PX_H = 480, 300


def _plane_rect():
    """A rectangle on the world XY plane, wound so it takes away the half
    above it (as in test_a_clipping_plane_caps_what_it_cuts.py)."""
    return g.planar_face(g.make_polyline(
        [(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)],
        closed=True))


def _detail(view: str, mode: str) -> DetailView:
    az, el = STANDARD_VIEWS[view]
    return DetailView(x=20.0, y=40.0, w=240.0, h=150.0, azimuth=az,
                      elevation=el, target=[0.0, 0.0, 0.0], scale_denom=1.0,
                      display_mode=mode)


@pytest.fixture
def cut(_qapp):
    """A blue box cut through its middle by a live clipping plane, with a
    sheet to draw details on, on a real GL surface.

    Never offscreen, where a shown pane can compile its shaders and then
    crash the whole run making the PDF's framebuffer. Run these with
    QT_QPA_PLATFORM=xcb on a display, as the cap tests are."""
    if _qapp.platformName() == "offscreen":
        pytest.skip("no real GL surface offscreen (CI runs offscreen)")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    vp = w.viewport
    vp.grabFramebuffer()            # makes the context, where there is one
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        w.mark_saved()
        w.close()
        pytest.skip("no GL 3.3 to draw with here (CI runs offscreen)")
    layer = w.scene.layers.create("Box", color=(0.0, 0.0, 1.0))
    box = w.scene.add(g.make_box((-20, -20, -20), 40, 40, 40))
    w.scene.update(box.id, layer_id=layer.id)
    plane = w.scene.add(_plane_rect(), name="Clip")
    w.scene.update(plane.id, clip_plane={"enabled": True})
    lay = Layout(name="Sheet")
    w.scene.layouts.append(lay)
    w.scene.notify()
    w.switch_space(lay.id)
    yield w, vp, lay, layer.id, plane.id
    w.mark_saved()
    w.close()


def _near(vp, det, image, point, test, reach=2) -> bool:
    """Whether a pixel within `reach` of where `point` of the model is
    drawn passes `test`: a one-pixel edge lands a pixel either way."""
    proj, view = vp.layout_view.detail_matrices(det, PX_W, PX_H)
    clip = proj @ view @ np.array([*point, 1.0])
    x, y = clip[:2] / clip[3]
    cx = int(round((x + 1) / 2 * image.width()))
    cy = int(round((1 - y) / 2 * image.height()))
    return any(test(image.pixelColor(cx + dx, cy + dy))
               for dx in range(-reach, reach + 1)
               for dy in range(-reach, reach + 1))


def _blue(c) -> bool:
    return c.blue() > 150 and c.red() < 100 and c.green() < 100


def _red(c) -> bool:
    return c.red() > 150 and c.green() < 100 and c.blue() < 100


def _ink(c) -> bool:
    return c.red() + c.green() + c.blue() < 200


@pytest.mark.parametrize("mode, kept, taken, drawn", [
    # the box's front face a quarter of the way up and down
    ("shaded", (0.0, -20.0, -10.0), (0.0, -20.0, 10.0), _blue),
    # and its left edge at the same heights, in ink on the paper
    ("wireframe", (-20.0, -20.0, -10.0), (-20.0, -20.0, 10.0), _ink),
])
def test_a_detail_takes_the_cut_the_model_view_takes(cut, mode, kept, taken,
                                                     drawn):
    w, vp, lay, layer_id, plane_id = cut
    det = _detail("front", mode)
    lay.details.append(det)

    w.scene.update(plane_id, clip_plane={"enabled": False})
    whole = vp.render_detail_image(det, PX_W, PX_H)
    assert whole is not None
    assert _near(vp, det, whole, kept, drawn) and \
        _near(vp, det, whole, taken, drawn), \
        "the box never drew whole, so the test proves nothing"

    w.scene.update(plane_id, clip_plane={"enabled": True})
    image = vp.render_detail_image(det, PX_W, PX_H)
    assert _near(vp, det, image, kept, drawn), "the kept half went too"
    assert not _near(vp, det, image, taken, drawn), \
        "the detail drew the half the clipping plane takes away"


def test_a_shaded_detail_caps_what_the_plane_cuts(cut):
    w, vp, lay, layer_id, plane_id = cut
    w.scene.layers.set_hatch(layer_id, "solid")
    w.scene.layers.set_hatch_color(layer_id, (1.0, 0.0, 0.0))
    det = _detail("top", "shaded")
    lay.details.append(det)
    w.scene.notify()

    image = vp.render_detail_image(det, PX_W, PX_H)
    assert _near(vp, det, image, (5.0, 5.0, 0.0), _red, reach=0), \
        "the cut was not capped"


def test_lines_in_a_detail_are_as_wide_as_they_say(cut, monkeypatch):
    """A wide line is widened in the shader against the size of the
    picture it is drawn into, so a detail has to give its own size, or a
    2-pixel cut line in a picture twice the pane's width comes out 1
    pixel wide."""
    w, vp, lay, layer_id, plane_id = cut
    det = _detail("top", "shaded")
    lay.details.append(det)
    w.scene.notify()
    sizes = []
    real = vp._set_uniform

    def watched(prog, name, setter, *values):
        if name == "uViewport":
            sizes.append(values)
        return real(prog, name, setter, *values)

    monkeypatch.setattr(vp, "_set_uniform", watched)
    vp.render_detail_image(det, PX_W, PX_H)

    assert sizes, "no wide line was drawn, so the test proves nothing"
    assert set(sizes) == {(float(PX_W), float(PX_H))}


# --- without a GL surface --------------------------------------------------

@pytest.fixture
def pane():
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    return Viewport(scene, SelectionManager(scene))


def test_a_detail_is_handed_the_clipping_planes(pane, monkeypatch):
    """What the GL tests above check by eye, checked where CI can run it:
    drawing the model while the pane shows a sheet passes the planes on."""
    obj = pane.scene.add(_plane_rect(), name="Clip")
    pane.scene.update(obj.id, clip_plane={"enabled": True})
    pane.space = "a-layout-id"
    handed = []
    monkeypatch.setattr(pane, "_draw_objects_with_clips",
                        lambda mvp, view, clips, *rest: handed.append(clips))
    monkeypatch.setattr(pane, "_end_clips", lambda clips: None)

    pane._draw_objects(np.eye(4), np.eye(4))

    assert len(handed) == 1 and len(handed[0]) == 1
    assert np.allclose(handed[0], pane._clip_vectors())


def test_a_detail_s_cap_is_hatched_at_its_spacing_on_the_sheet(pane):
    """A hidden-line detail hatches its cut at the layer's spacing in
    paper millimetres; a shaded one does too, so the two read alike on
    one sheet and print alike. At 1:50 a 2.5mm hatch is 125 units apart
    in the model, however far the sheet is zoomed."""
    from serpentine3d.ui import section_caps as caps
    with pane._into_detail(480, 300, 1.0, scale_denom=50.0, px_per_mm=2.0):
        assert pane._cap_period(2.5, 0.7) == pytest.approx(125.0)
        assert pane._cap_period(2.5, 7.0) == pytest.approx(125.0)
        assert pane._cap_period(0.0, 7.0) is None
    with pane._into_detail(480, 300, 1.0, px_per_mm=2.0):    # perspective
        assert pane._cap_period(2.5, 7.0) == caps.hatch_period(2.5, 7.0)
    assert pane._cap_period(2.5, 7.0) == caps.hatch_period(2.5, 7.0)


def test_a_detail_is_measured_as_the_picture_it_is(pane):
    """Line widths and a cap's pixels are measured against what is being
    drawn: the detail while it is, and the pane again afterwards."""
    pane.resize(640, 480)
    assert pane._target_size() == (640.0, 480.0)
    with pane._into_detail(300, 200, 2.0, scale_denom=10.0, px_per_mm=1.25,
                           view="d1"):
        target = pane._draw_target()
        assert tuple(target) == (300.0, 200.0, 2.0, 10.0, 1.25, "d1")
        assert pane._target_size() == (300.0, 200.0)
    assert pane._target_size() == (640.0, 480.0)
    assert pane._draw_target().scale_denom is None
    assert pane._draw_target().px_per_mm is None


def test_a_cut_line_in_a_detail_is_its_print_width_on_the_sheet():
    """A hidden-line detail draws a cut line at its width in millimetres
    on the sheet, and so does a shaded one now: 0.5mm at 4 pixels to the
    sheet's millimetre is 2 pixels, whatever the screen's own pen says.
    Never under a pixel, as on screen."""
    from serpentine3d.core.layout import SectionFill
    from serpentine3d.ui import section_caps as caps
    fill = SectionFill(cut_line_width=0.5)
    _color, on_screen = caps.cut_line_style(fill)
    assert caps.cut_line_style(fill, px_per_mm=4.0)[1] == pytest.approx(2.0)
    assert caps.cut_line_style(fill, px_per_mm=0.5)[1] == 1.0
    assert caps.cut_line_style(fill)[1] == on_screen
    assert caps.cut_line_style(SectionFill(cut_line_width=0.0),
                               px_per_mm=4.0) is None


# --- a hidden-line detail ----------------------------------------------------
#
# What the `detail` command places, so the case #94 was about. Its lines
# come from OpenCASCADE's hidden-line pass rather than the GPU, so the
# planes cut the shapes themselves first, as a detail's own section does,
# and the faces they leave on a solid are hatched like that section's.

@pytest.fixture
def hidden(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((-20, -20, -20), 40, 40, 40))
    plane = w.scene.add(_plane_rect(), name="Clip")
    w.scene.update(plane.id, clip_plane={"enabled": True})
    lay = Layout(name="Sheet")
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    yield w, w.viewport.layout_view, lay, box.id, plane.id
    w.mark_saved()
    w.close()


def _box_lines(lv, det, box_id):
    """Every point of the box's visible lines, in the detail's frame."""
    pts = [p for oid, _lt, polys in lv._detail_hlr(det)["visible_by_obj"]
           if oid == box_id for poly in polys for p in poly]
    assert pts, "the box drew nothing, so the test proves nothing"
    return np.asarray(pts, float)


def test_a_hidden_line_detail_takes_the_cut(hidden):
    """Seen from the front the detail's up is the model's z, so the box
    reaches 20 above the plane whole and nothing above it once cut."""
    w, lv, lay, box_id, plane_id = hidden
    det = _detail("front", "hidden")
    lay.details.append(det)

    w.scene.update(plane_id, clip_plane={"enabled": False})
    assert _box_lines(lv, det, box_id)[:, 1].max() == pytest.approx(20.0)

    w.scene.update(plane_id, clip_plane={"enabled": True})
    lines = _box_lines(lv, det, box_id)
    assert lines[:, 1].max() == pytest.approx(0.0, abs=1e-6), \
        "the detail drew the half the clipping plane takes away"
    assert lines[:, 1].min() == pytest.approx(-20.0)


def test_the_face_a_plane_leaves_is_hatched(hidden):
    """Looking straight down the plane, the box's cut is a 40-unit square,
    hatched in whatever the box's layer hatches its cuts with."""
    w, lv, lay, box_id, plane_id = hidden
    det = _detail("top", "hidden")
    lay.details.append(det)

    cuts = [(oid, region) for oid, _pattern, region
            in lv._detail_hlr(det)["cut_by_obj"]]
    assert [oid for oid, _ in cuts] == [box_id]
    outside = np.asarray(cuts[0][1][0], float)
    assert outside.min(axis=0) == pytest.approx((-20.0, -20.0), abs=1e-3)
    assert outside.max(axis=0) == pytest.approx((20.0, 20.0), abs=1e-3)


def test_a_paused_or_hidden_plane_leaves_the_detail_whole(hidden):
    """The detail's lines are cached, so this is also that the cache
    hears of it: hiding a layer does not change the scene's revision."""
    w, lv, lay, box_id, plane_id = hidden
    det = _detail("front", "hidden")
    lay.details.append(det)
    assert _box_lines(lv, det, box_id)[:, 1].max() < 1.0

    layer = w.scene.layers.create("Planes")
    w.scene.update(plane_id, layer_id=layer.id)
    assert _box_lines(lv, det, box_id)[:, 1].max() < 1.0
    w.scene.layers.set_visible(layer.id, False)
    assert _box_lines(lv, det, box_id)[:, 1].max() == pytest.approx(20.0)
    assert lv._detail_hlr(det)["cut_by_obj"] == []

    w.scene.layers.set_visible(layer.id, True)
    w.scene.update(plane_id, clip_plane={"enabled": False})
    assert _box_lines(lv, det, box_id)[:, 1].max() == pytest.approx(20.0)


def test_the_plane_itself_still_draws(hidden):
    """A plane is not cut by itself: it lies on the face it would cut
    with, and could come back whole or vanish on rounding. It draws as it
    does in every other view, and its layer can be left out of a detail
    (#38) for a clean section that still cuts."""
    w, lv, lay, box_id, plane_id = hidden
    det = _detail("top", "hidden")
    lay.details.append(det)
    drawn = {oid for oid, _lt, polys in lv._detail_hlr(det)["visible_by_obj"]
             if polys}
    assert plane_id in drawn

    layer = w.scene.layers.create("Planes")
    w.scene.update(plane_id, layer_id=layer.id)
    det.hidden_layers = [layer.id]
    data = lv._detail_hlr(det)
    assert plane_id not in {oid for oid, _lt, _p in data["visible_by_obj"]}
    assert [oid for oid, _p, _r in data["cut_by_obj"]] == [box_id]


def test_a_section_still_cuts_what_the_plane_left(hidden):
    """A detail's own section (detailsection) and a clipping plane can be
    on at once: the section is taken through what the plane left."""
    w, lv, lay, box_id, plane_id = hidden
    det = _detail("front", "hidden")
    det.section_offset = 0.0        # through the middle, facing the eye
    lay.details.append(det)
    data = lv._detail_hlr(det)
    sections = [np.asarray(region[0], float)
                for oid, _p, region in data["cut_by_obj"] if oid == box_id]
    assert sections, "the section cut nothing"
    tallest = max(s[:, 1].max() for s in sections)
    assert tallest == pytest.approx(0.0, abs=1e-3), \
        "the section was taken through the half the plane took away"


def test_a_detail_the_plane_is_switched_off_in_draws_whole(cut):
    """A plane switched off in one detail (core/clipping.py) leaves that
    detail whole, on the sheet and in the PDF, and still cuts the rest."""
    from serpentine3d.core import clipping
    w, vp, lay, layer_id, plane_id = cut
    off = _detail("front", "shaded")
    on = _detail("front", "shaded")
    lay.details.extend([off, on])
    clipping.switch(w.scene, plane_id, off.id, False)
    taken = (0.0, -20.0, 10.0)
    assert _near(vp, off, vp.render_detail_image(off, PX_W, PX_H), taken,
                 _blue), "the detail the plane is off in was cut"
    assert not _near(vp, on, vp.render_detail_image(on, PX_W, PX_H), taken,
                     _blue), "switching it off in one detail took it out of all"
