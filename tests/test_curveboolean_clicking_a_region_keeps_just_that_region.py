"""A click keeps the one region it landed in, and a second click lets go.

Rhino's CurveBoolean is a bucket fill: click inside the area you want, and
only that area comes back. Clicking it again removes it, so a region can be
chosen and unchosen before Enter spends the pick.
"""

import math

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_clicking_the_overlap_keeps_just_the_overlap(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide((1.0, 0.0, 0.0))    # inside both circles, and nothing else
    proc.provide_text("")            # Enter: finish
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    lens = 8 * math.pi / 3 - 2 * math.sqrt(3)
    area = g.surface_area(g.planar_face(curves[0].shape))
    assert area == pytest.approx(lens, rel=1e-3)
    assert a.id not in scene.objects and b.id not in scene.objects
    assert selection.ids == [curves[0].id]


def test_a_second_click_on_the_same_region_removes_it(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide((1.0, 0.0, 0.0))    # keep the lens
    proc.provide((1.0, 0.0, 0.0))    # ...no, let it go
    proc.provide_text("")            # Enter with nothing kept
    assert not proc.busy
    assert scene.get(a.id) is not None and scene.get(b.id) is not None
    assert [o.id for o in scene.all() if o.kind == "curve"] == [a.id, b.id]
    assert selection.ids == []


def test_a_click_outside_every_region_keeps_asking(env):
    scene, selection, _history, ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    said = []
    ctx.add_echo_listener(said.append)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide((6.0, 0.0, 0.0))    # out past the rim
    assert proc.busy, "a miss must not end the pick"
    assert any("inside a region" in line for line in said)
    proc.provide_text("")            # Enter with nothing kept: cancel
    assert not proc.busy


def test_a_click_on_a_curve_itself_keeps_nothing(env):
    """The rim of a region is shared with its neighbour, so only an
    interior click may choose it — a click on the curve says so."""
    scene, selection, _history, ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    said = []
    ctx.add_echo_listener(said.append)
    selection.set([a.id, b.id])
    proc.run("curveboolean")
    proc.provide((0.0, 2.0, 0.0))    # on the outer rim of the union
    assert proc.busy, "a click on the rim must not end the pick"
    assert any("on a curve" in line for line in said)
    proc.provide_text("")            # Enter with nothing kept: cancel
    assert not proc.busy
    assert scene.get(a.id) is not None and scene.get(b.id) is not None
