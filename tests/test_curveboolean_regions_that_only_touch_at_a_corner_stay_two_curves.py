"""Regions that only touch at a point stay two curves.

Two squares sharing a corner divide the plane into two regions whose
outlines meet at a single point. A cut that falls through a point does
not join outlines, so CurveBoolean hands them back as two closed curves
touching there — the same shape Rhino's single figure-eight curve would
be, just carried as two curves.
"""

import pytest

from serpentine3d.core import geometry as g


def test_squares_that_share_a_corner_come_back_as_two_curves(env):
    scene, selection, _history, _ctx, proc = env
    a = scene.add(g.make_rectangle((0.0, 0.0, 0.0), (2.0, 2.0, 0.0)))
    b = scene.add(g.make_rectangle((2.0, 2.0, 0.0), (4.0, 4.0, 0.0)))
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide_text("All")
    proc.provide_text("")            # Enter: finish
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 2
    areas = sorted(g.surface_area(g.planar_face(c.shape)) for c in curves)
    assert areas == pytest.approx([4.0, 4.0], rel=1e-3)
    assert a.id not in scene.objects and b.id not in scene.objects
    assert sorted(selection.ids) == sorted(c.id for c in curves)
