"""Boundary mode is off for a single closed curve: it stands as it is.

CurveBoolean's region business exists to combine several curves. One closed
curve has no other boundary to boolean with, so the command passes it
through — no pick, nothing eaten, nothing re-created — and open curves are
told they cannot play, since a region needs a closed boundary.
"""

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_one_closed_curve_is_passed_through_and_left_selected(env):
    scene, selection, _history, ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    selection.set([a.id])
    said = []
    ctx.add_echo_listener(said.append)
    proc.run("curveboolean")
    assert not proc.busy, "nothing to pick, nothing to wait for"
    assert [o for o in scene.all() if o.kind == "curve"] == [a]
    assert selection.ids == [a.id]
    assert any("boundary mode off" in line for line in said)


def test_open_curves_are_skipped_and_none_left_cancels(env):
    scene, selection, _history, ctx, proc = env
    open_curve = scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    selection.set([open_curve.id])
    said = []
    ctx.add_echo_listener(said.append)
    proc.run("curveboolean")
    assert not proc.busy
    assert scene.get(open_curve.id) is not None
    assert selection.ids == []
    assert any("open curve" in line for line in said)


def test_one_closed_curve_survives_among_open_ones(env):
    scene, selection, _history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    open_curve = scene.add(g.make_line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
    selection.set([a.id, open_curve.id])
    proc.run("curveboolean")
    assert not proc.busy
    assert scene.get(a.id) is not None and scene.get(open_curve.id) is not None
    assert selection.ids == [a.id], "the boundary curve is what you hold"
