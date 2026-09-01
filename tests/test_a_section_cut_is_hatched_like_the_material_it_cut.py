"""A cut face is filled with the material the saw went through.

A section drawing is read by its fills: concrete crosses, steel blacks
in, insulation does neither. Every cut face in a detail came out under
the same 45 degree lines whatever it had been cut from, because the cut
threw away which object each region belonged to on the way out. It
carries the object with it now, so the layer that object is on says what
its cut looks like, on screen and on the plot.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import cut_hatching
from serpentine3d.ui.layout_view import _section_cut

import numpy as np


SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0)]


def _cut(shapes, target=(0.0, 0.0, 15.0)):
    """The cut a top-down detail makes, plane through the target."""
    return _section_cut(shapes, np.asarray(target, float),
                        np.array([0.0, 0.0, 1.0]),
                        np.array([1.0, 0.0, 0.0]),
                        np.array([0.0, 1.0, 0.0]), 0.0)


# -- the cut says what it cut ---------------------------------------------

def test_a_cut_region_says_which_shape_it_came_from():
    near = g.make_box((-20, -5, 0), 10, 10, 30)
    far = g.make_box((20, -5, 0), 10, 10, 30)
    _shapes, regions, owners = _cut([near, far])
    assert len(regions) == 2
    assert owners == [0, 1], \
        "the regions came back in a heap with nothing to say whose they are"


def test_a_shape_the_plane_never_reaches_owns_nothing():
    """Owners point at the shape, so a shape that is not cut is skipped."""
    face = g.planar_face(g.make_polyline(
        [(0, 0, 15), (10, 0, 15), (10, 10, 15), (0, 10, 15)], closed=True))
    box = g.make_box((-20, -5, 0), 10, 10, 30)
    _shapes, regions, owners = _cut([face, box])
    assert len(regions) == 1
    assert owners == [1], "the surface was credited with the box's cut face"


def test_one_shape_cut_in_two_places_owns_both_faces():
    """Two bars in one object are one material, both times."""
    pair = g.boolean_union(g.make_box((-20, -5, 0), 10, 10, 30),
                           g.make_box((20, -5, 0), 10, 10, 30))
    _shapes, regions, owners = _cut([pair])
    assert len(regions) == 2
    assert owners == [0, 0]


# -- and the fill follows from it -----------------------------------------

def _hatch(pattern, region=(SQUARE,)):
    return cut_hatching([list(region)], 0.0, 0.0, 1.0,
                        patterns=[pattern])


def _directions(fill):
    """The directions the hatch lines run in, rounded to the degree."""
    import math
    return {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))) % 180
            for a, b in fill}


def test_a_cut_with_nothing_to_say_is_hatched_the_way_it_always_was():
    """Most layers name no material, and those cuts must not change."""
    fill, loops, solid = _hatch("")
    was_fill, was_loops = cut_hatching([[SQUARE]], 0.0, 0.0, 1.0)[:2]
    assert fill == was_fill and loops == was_loops and solid == []


def test_lines_and_no_pattern_at_all_come_out_the_same():
    assert _hatch("lines")[0] == _hatch("")[0]


def test_cross_hatches_the_same_face_twice():
    lines = _directions(_hatch("lines")[0])
    cross = _directions(_hatch("cross")[0])
    assert len(lines) == 1, "the plain fill runs in more than one direction"
    assert len(cross) == 2, "cross hatching came out as one set of lines"
    assert lines < cross, "cross dropped the direction lines already ran in"


def test_solid_fills_the_face_instead_of_lining_it():
    fill, _loops, solid = _hatch("solid")
    assert fill == [], "a solid fill was drawn as hatch lines"
    assert solid == [[[(x, y) for x, y in SQUARE]]], \
        "nothing was handed over to be filled, so the face draws empty"


def test_a_solid_cut_keeps_its_bore_open():
    """Solid is one shape with holes in it, the same as a solid hatch."""
    _fill, _loops, solid = _hatch("solid", (SQUARE, HOLE))
    assert len(solid) == 1 and len(solid[0]) == 2, \
        "the bore was handed over as material, so the pipe fills in"


def test_every_cut_is_outlined_whatever_it_is_filled_with():
    for pattern in ("", "lines", "cross", "solid"):
        assert len(_hatch(pattern, (SQUARE, HOLE))[1]) == 2, \
            f"a {pattern or 'plain'} cut lost the line round one of its rings"


def test_a_pattern_the_app_cannot_draw_is_hatched_like_any_other_cut():
    """A file can name anything; a cut face still has to be drawn."""
    assert _hatch("herringbone")[0] == _hatch("")[0]


def test_each_region_is_filled_with_its_own_material():
    other = [(30.0, -10.0), (50.0, -10.0), (50.0, 10.0), (30.0, 10.0)]
    fill, _loops, solid = cut_hatching([[SQUARE], [other]], 0.0, 0.0, 1.0,
                                       patterns=["solid", "lines"])
    assert len(solid) == 1, "the steel and the concrete were filled the same"
    assert fill and all(a[0] > 20.0 and b[0] > 20.0 for a, b in fill), \
        "the face that was to be filled solid got hatch lines as well"


# -- end to end, through a detail on a sheet -------------------------------

@pytest.fixture
def sectioned_sheet():
    """Two bars side by side, cut, each on a layer of its own."""
    from serpentine3d.app import MainWindow
    from serpentine3d.core.layout import DetailView, Layout
    from serpentine3d.ui.camera import STANDARD_VIEWS

    w = MainWindow()
    w.resize(1200, 800)
    concrete = w.scene.layers.create("Concrete")
    steel = w.scene.layers.create("Steel")
    w.scene.layers.set_hatch(concrete.id, "cross")
    w.scene.layers.set_hatch(steel.id, "solid")
    left = w.scene.add(g.make_box((-60.0, -20.0, 0.0), 40.0, 40.0, 40.0))
    right = w.scene.add(g.make_box((20.0, -20.0, 0.0), 40.0, 40.0, 40.0))
    w.scene.update(left.id, layer_id=concrete.id)
    w.scene.update(right.id, layer_id=steel.id)
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=40.0, y=60.0, w=200.0, h=150.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 20.0], scale_denom=2.0,
                     display_mode="hidden", section_offset=0.0)
    lay = Layout(name="Sheet1")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    return w, lv, det, left, right


def _patterns_by_object(data):
    return {oid: pattern for oid, pattern, _region in data["cut_by_obj"]}


def test_a_cut_is_filled_with_the_material_of_the_layer_it_cut(
        sectioned_sheet):
    _w, lv, det, left, right = sectioned_sheet
    by_object = _patterns_by_object(lv._detail_hlr(det))
    assert by_object[left.id] == "cross"
    assert by_object[right.id] == "solid", \
        "both bars were filled the same, so the drawing says nothing"


def test_a_layer_with_nothing_to_say_leaves_its_cut_on_lines(sectioned_sheet):
    w, lv, det, left, _right = sectioned_sheet
    w.scene.layers.set_hatch(w.scene.get(left.id).layer_id, "")
    lv._hlr_cache.clear()
    assert _patterns_by_object(lv._detail_hlr(det))[left.id] == ""


def test_the_cut_the_pickers_read_is_the_cut_that_gets_filled(
        sectioned_sheet):
    """One list, so a click and the fill cannot land on different faces."""
    _w, lv, det, _left, _right = sectioned_sheet
    data = lv._detail_hlr(det)
    assert [region for _oid, _p, region in data["cut_by_obj"]] == data["cut"]
