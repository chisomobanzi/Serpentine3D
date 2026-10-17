"""CurveBoolean of overlapping curves comes back as one merged outline.

The whole point of the command is turning a pile of overlapping planar
curves into clean closed profiles. Keeping every region — All, or Alt+A,
which feeds the same word — hands back a single closed curve around the
outside of the union, the internal seams fused away, and the inputs are
eaten the way a solid boolean eats the solids it combined.
"""

import math

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_all_regions_of_two_overlapping_circles_make_one_outline(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide_text("All")
    proc.provide_text("")            # Enter: finish
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    # the union of two r=2 circles whose centres are 2 apart
    lens = 8 * math.pi / 3 - 2 * math.sqrt(3)
    union = 8 * math.pi - lens
    area = g.surface_area(g.planar_face(curves[0].shape))
    assert area == pytest.approx(union, rel=1e-3)
    # the inputs are gone, the result is held, on the first curve's layer
    assert a.id not in scene.objects and b.id not in scene.objects
    assert selection.ids == [curves[0].id]
    assert curves[0].layer_id == a.layer_id


def test_the_result_curve_is_closed_and_fits_the_inputs(env):
    """The output has to extrude: closed, planar, and the same size as
    what went in, not a polyline shrunken around the corners."""
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide_text("All")
    proc.provide_text("")
    curve = next(o for o in scene.all() if o.kind == "curve")
    assert g.is_closed_curve(curve.shape)
    (lo, hi) = g.bbox(curve.shape)
    # the union of the two r=2 circles spans -2..4 in x, -2..2 in y
    assert hi[0] == pytest.approx(4.0, abs=1e-6)
    assert lo[0] == pytest.approx(-2.0, abs=1e-6)
    assert hi[1] == pytest.approx(2.0, abs=1e-6)
    assert lo[1] == pytest.approx(-2.0, abs=1e-6)
