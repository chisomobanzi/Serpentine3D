"""A curve drawn over itself does not double its region.

Two curves that describe the same place would divide the plane into the
same region twice, and a click could not choose between them. The
arrangement drops the duplicate face, so the pick sees each region once
and All keeps one outline, not two.
"""

import math

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_two_copies_of_the_same_circle_boolean_to_one_curve(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 0.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide_text("All")
    proc.provide_text("")            # Enter: finish
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    area = g.surface_area(g.planar_face(curves[0].shape))
    assert area == pytest.approx(4 * math.pi, rel=1e-3)
    assert a.id not in scene.objects and b.id not in scene.objects
