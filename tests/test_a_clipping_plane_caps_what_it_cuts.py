"""A clipping plane closes the solids it cuts with a cap, hatched (#40).

A clipping plane used to leave a solid hollow: the shader drops whatever
is past the plane, and what was inside the solid showed as the backs of
its own faces. Now the cut face is drawn the way a section drawing draws
it, filled and hatched the way the solid's layer, or the solid itself,
says, and it follows the plane as it moves because the GPU works it out
each frame rather than OpenCASCADE.

The pure parts are tested here: which planes and which objects, the
basis a hatch is laid out in, how the cap is coloured, and how far apart
the hatch's lines fall at a given zoom. The drawing itself needs a real
GL surface, so those tests skip without one (CI runs offscreen); run them
with QT_QPA_PLATFORM=xcb on a display.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core.layout import SectionFill
from serpentine3d.ui import section_caps as caps


# -- the planes ---------------------------------------------------------------

def test_only_live_planes_cap_and_no_more_than_the_shader_clips():
    frames = [((0, 0, i), (0, 0, 1), i != 1) for i in range(6)]
    planes = caps.cap_planes(frames)
    assert [p.origin[2] for p in planes] == [0, 2, 3, 4], \
        "a paused plane capped, or more planes than the shader clips with"


def test_each_cap_plane_keeps_the_clip_equation_the_shader_uses():
    from serpentine3d.ui.viewport import clip_equation
    (plane,) = caps.cap_planes([((1.0, 2.0, 3.0), (0.0, 0.0, 1.0), True)])
    assert np.allclose(plane.equation, clip_equation((1, 2, 3), (0, 0, 1)))


@pytest.mark.parametrize("normal", [(0, 0, 1), (0, 0, -1), (1, 0, 0),
                                    (0, -1, 0), (1, 1, 1)])
def test_the_hatch_is_laid_out_square_on_the_plane(normal):
    n = np.asarray(normal, float) / np.linalg.norm(normal)
    u, v = caps.plane_axes(n)
    assert np.isclose(np.linalg.norm(u), 1)
    assert np.isclose(np.linalg.norm(v), 1)
    assert abs(np.dot(u, n)) < 1e-9 and abs(np.dot(v, n)) < 1e-9
    assert np.allclose(np.cross(u, v), n), \
        "seen from the cut side the hatch would come out mirrored"


def test_a_wall_s_cut_is_hatched_from_its_horizontal():
    """On a vertical plane `u` runs level, the way a section is read."""
    u, _v = caps.plane_axes(np.array([0.0, 1.0, 0.0]))
    assert abs(u[2]) < 1e-9


# -- the objects --------------------------------------------------------------

BOX = ((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))


@pytest.mark.parametrize("height, cuts", [(5.0, True), (-1.0, False),
                                          (11.0, False), (10.0, False)])
def test_a_plane_caps_only_what_it_passes_through(height, cuts):
    assert caps.straddles(BOX, (0.0, 0.0, height), (0.0, 0.0, 1.0)) is cuts


def test_a_tilted_plane_through_a_corner_still_cuts():
    assert caps.straddles(BOX, (9.5, 9.5, 9.5), (1.0, 1.0, 1.0))


# -- the look -----------------------------------------------------------------

GREY = (0.8, 0.8, 0.8)


def test_lines_on_a_shade_of_the_object_in_ink():
    style = caps.cap_style(SectionFill("lines", 30.0, 2.0), GREY)
    assert style.pattern == caps.LINES
    assert style.fill == pytest.approx(tuple(c * caps.CUT_SHADE for c in GREY))
    assert style.line[:3] == pytest.approx(caps.INK_ON_SCREEN)
    assert style.angle == pytest.approx(math.radians(30.0))
    assert style.spacing_mm == 2.0


def test_a_hatch_in_a_colour_draws_its_lines_in_it():
    style = caps.cap_style(SectionFill("cross", color=(1.0, 0.0, 0.0)), GREY)
    assert style.pattern == caps.CROSS
    assert style.line[:3] == pytest.approx((1.0, 0.0, 0.0))


def test_solid_floods_the_cap_in_its_colour_or_a_dark_poche():
    red = caps.cap_style(SectionFill("solid", color=(1.0, 0.0, 0.0)), GREY)
    assert red.pattern == caps.SOLID and red.fill == pytest.approx((1, 0, 0))
    assert red.line[3] == 0
    ink = caps.cap_style(SectionFill("solid"), GREY)
    assert ink.fill == pytest.approx(tuple(c * caps.POCHE_SHADE
                                           for c in GREY))


def test_none_still_closes_the_solid_without_lines():
    """None leaves a cut empty on paper; in the model the solid must still
    read as solid, so the cap is there, plain."""
    style = caps.cap_style(SectionFill("none"), GREY)
    assert style.pattern == caps.PLAIN and style.line[3] == 0


def test_caps_that_look_alike_are_drawn_together():
    a = caps.cap_style(SectionFill("cross"), GREY)
    b = caps.cap_style(SectionFill("cross"), GREY)
    c = caps.cap_style(SectionFill("lines"), GREY)
    groups = caps.group_by_style([("a", a), ("b", b), ("c", c)])
    assert [ids for _style, ids in groups] == [["a", "b"], ["c"]]


# -- the spacing on screen ----------------------------------------------------

def test_pixels_a_unit_takes_up_at_the_plane():
    # an orthographic view 100 units across a 200 px viewport
    mvp = np.diag([2.0 / 100.0, 2.0 / 100.0, 1.0, 1.0])
    assert caps.pixels_per_unit(mvp, (0, 0, 0), (1, 0, 0), 200, 200) \
        == pytest.approx(2.0)


def test_the_hatch_keeps_to_the_plane_and_steps_in_doublings():
    """Lines laid out in the model's units keep still on the cap while the
    view turns; the period only changes by doublings as the view zooms, so
    the hatch does not crawl."""
    periods = {caps.hatch_period(2.5, ppu) for ppu in np.linspace(1, 4, 40)}
    for p in periods:
        assert math.log2(p) == pytest.approx(round(math.log2(p)))
    assert len(periods) <= 3
    near = caps.hatch_period(2.5, 2.0) * 2.0      # its period in pixels
    target = 2.5 * caps.CAP_PX_PER_MM
    assert target / math.sqrt(2) - 1e-9 <= near <= target * math.sqrt(2)


def test_no_period_without_a_scale_to_read():
    assert caps.hatch_period(2.5, 0.0) is None


# -- the drawing --------------------------------------------------------------

@pytest.fixture
def cut_box(_qapp):
    """A box cut through its middle by a live clipping plane, looked at
    straight down the plane's normal, on a real GL surface."""
    from serpentine3d.app import MainWindow
    from serpentine3d.core import geometry as g
    w = MainWindow()
    w.set_view_layout("single")
    w.resize(900, 700)
    w.show()
    vp = w.viewport
    vp.grabFramebuffer()            # makes the context, where there is one
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        # Offscreen, Qt hands back an image and a GL 2.0 context all the
        # same, but the viewport's own shaders never compile on it: only
        # they say whether this viewport can really draw.
        w.mark_saved()
        w.close()
        pytest.skip("no GL 3.3 to draw with here (CI runs offscreen)")
    box = w.scene.add(g.make_box((-20, -20, -20), 40, 40, 40))
    rect = g.make_polyline([(-60, -60, 0), (60, -60, 0), (60, 60, 0),
                            (-60, 60, 0)], closed=True)
    plane = w.scene.add(g.planar_face(rect), name="Clip")
    w.scene.update(plane.id, clip_plane={"enabled": True})
    w.scene.notify()
    vp.set_view("top")
    vp.zoom_extents()
    yield w, vp, box
    w.mark_saved()
    w.close()


def _centre(image):
    """A pixel well inside the cut face, off the plane's own arrow, which
    stands at the middle of the plane and, seen end on, is a dot there."""
    return image.pixelColor(image.width() // 2 + image.width() // 14,
                            image.height() // 2 + image.height() // 14)


def test_the_cut_through_a_box_is_capped(cut_box):
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "solid")
    w.scene.layers.set_hatch_color(box.layer_id, "#ff0000")
    w.scene.notify()
    centre = _centre(vp.grabFramebuffer())
    assert (centre.red(), centre.green(), centre.blue()) == \
        pytest.approx((255, 0, 0), abs=12), \
        f"the box is hollow where it is cut: {centre.name()}"


def test_a_paused_plane_leaves_the_box_whole(cut_box):
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "solid")
    w.scene.layers.set_hatch_color(box.layer_id, "#ff0000")
    plane = next(o for o in w.scene.all() if o.clip_plane)
    w.scene.update(plane.id, clip_plane={"enabled": False})
    w.scene.notify()
    centre = _centre(vp.grabFramebuffer())
    assert centre.red() < 200 or centre.green() > 60, \
        "a cap was drawn on a plane that is not cutting"


def test_wireframe_draws_no_cap(cut_box):
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "solid")
    w.scene.layers.set_hatch_color(box.layer_id, "#ff0000")
    vp.set_display_mode("wireframe")
    w.scene.notify()
    centre = _centre(vp.grabFramebuffer())
    assert not (centre.red() > 200 and centre.green() < 60), \
        "wireframe filled the cut in"


def _pixel_at(vp, image, point):
    """The grabbed pixel showing a point in the model."""
    (x, y, _w), = vp.camera.project(np.asarray([point], float),
                                    vp.width(), vp.height())
    scale = image.width() / max(vp.width(), 1)
    return image.pixelColor(int(round(x * scale)), int(round(y * scale)))


def _is_red(color):
    return color.red() > 200 and color.green() < 60 and color.blue() < 60


def test_two_solids_of_one_material_cap_where_they_overlap(cut_box):
    """Counted, not flipped: inside two at once is still inside."""
    from serpentine3d.core import geometry as g
    w, vp, box = cut_box
    other = w.scene.add(g.make_box((0, -20, -20), 40, 40, 40))
    w.scene.update(other.id, layer_id=box.layer_id)
    w.scene.layers.set_hatch(box.layer_id, "solid")
    w.scene.layers.set_hatch_color(box.layer_id, "#ff0000")
    w.scene.notify()
    vp.zoom_extents()
    image = vp.grabFramebuffer()
    for x in (-10.0, 10.0, 30.0):      # first only, both, second only
        seen = _pixel_at(vp, image, (x, 7.0, 0.0))
        assert _is_red(seen), f"no cap at x={x}: {seen.name()}"


def test_a_second_plane_trims_the_first_one_s_cap(cut_box):
    """Where another plane has cut the solid away there is nothing left to
    close, so the cap stops at it."""
    from serpentine3d.core import geometry as g
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "solid")
    w.scene.layers.set_hatch_color(box.layer_id, "#ff0000")
    # a wall of a plane at x = 10, taking away everything past it
    rect = g.make_polyline([(10, -60, -60), (10, 60, -60), (10, 60, 60),
                            (10, -60, 60)], closed=True)
    wall = w.scene.add(g.planar_face(rect), name="Clip 2")
    w.scene.update(wall.id, clip_plane={"enabled": True})
    w.scene.notify()
    image = vp.grabFramebuffer()
    assert _is_red(_pixel_at(vp, image, (-10.0, 7.0, 0.0)))
    beyond = _pixel_at(vp, image, (16.0, 7.0, 0.0))
    assert not _is_red(beyond), \
        f"the cap ran on past the second plane: {beyond.name()}"


def test_the_cap_is_outlined_in_its_cut_line_colour(cut_box):
    """The line round a cap, where the plane meets the solid's sides, in
    the width and colour its layer gives its cut line (#82)."""
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "none")
    w.scene.layers.set_cut_line_width(box.layer_id, 1.0)
    w.scene.layers.set_cut_line_color(box.layer_id, "#ff0000")
    w.scene.notify()
    image = vp.grabFramebuffer()
    edge = _pixel_at(vp, image, (20.0, 7.0, 0.0))
    assert _is_red(edge), f"no line round the cut: {edge.name()}"
    inside = _pixel_at(vp, image, (10.0, 7.0, 0.0))
    assert not _is_red(inside), \
        f"the line spread across the cap: {inside.name()}"


def test_a_cut_line_of_none_leaves_the_cap_unoutlined(cut_box):
    w, vp, box = cut_box
    w.scene.layers.set_hatch(box.layer_id, "none")
    w.scene.layers.set_cut_line_width(box.layer_id, 0.0)
    w.scene.layers.set_cut_line_color(box.layer_id, "#ff0000")
    w.scene.notify()
    edge = _pixel_at(vp, vp.grabFramebuffer(), (20.0, 7.0, 0.0))
    assert not _is_red(edge), f"a line of None was drawn: {edge.name()}"
