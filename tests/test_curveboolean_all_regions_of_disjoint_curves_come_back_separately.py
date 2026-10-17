"""Disjoint curves have nothing to merge, so each outline comes back alone.

Boundary mode on means the kept regions are combined into one outline where
they touch. Curves that never meet combine into nothing, and the boolean
then gives back exactly the outlines it was handed — one closed curve per
region, which is what a nest of separate profiles should extrude as.
"""

import math

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_all_of_two_disjoint_circles_make_two_curves(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 1.0)
    b = _circle(scene, 4.0, 0.0, 1.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide_text("All")
    proc.provide_text("")
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 2
    total = sum(g.surface_area(g.planar_face(c.shape)) for c in curves)
    assert total == pytest.approx(2 * math.pi, rel=1e-3)
    assert a.id not in scene.objects and b.id not in scene.objects
    assert sorted(selection.ids) == sorted(c.id for c in curves)
