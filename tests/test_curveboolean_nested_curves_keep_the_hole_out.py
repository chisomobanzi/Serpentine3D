"""Nested curves read as a ring around a hole, and the hole is its own pick.

A circle inside a circle is not two solid regions: it is a ring with a hole
in it, and clicking the ring keeps the outer rim and the hole's rim as two
curves — the same pair that would extrude a tube. Clicking the hole keeps
just the hole's rim.
"""

import math

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_clicking_the_ring_keeps_outer_rim_and_hole_rim(env):
    scene, selection, _history, _ctx, proc = env
    outer = _circle(scene, 0.0, 0.0, 2.0)
    inner = _circle(scene, 0.0, 0.0, 1.0)
    selection.set([outer.id, inner.id])
    proc.run("curveboolean")
    proc.provide((1.5, 0.0, 0.0))    # in the ring, outside the hole
    proc.provide_text("")
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 2
    lengths = sorted(g.curve_length(c.shape) for c in curves)
    assert lengths == pytest.approx([2 * math.pi, 4 * math.pi], rel=1e-3)
    assert outer.id not in scene.objects and inner.id not in scene.objects
    assert sorted(selection.ids) == sorted(c.id for c in curves)


def test_clicking_the_hole_keeps_just_the_hole(env):
    scene, selection, _history, _ctx, proc = env
    outer = _circle(scene, 0.0, 0.0, 2.0)
    inner = _circle(scene, 0.0, 0.0, 1.0)
    selection.set([outer.id, inner.id])
    proc.run("curveboolean")
    proc.provide((0.5, 0.0, 0.0))    # inside the hole, not the ring
    proc.provide_text("")
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(2 * math.pi,
                                                            rel=1e-3)
