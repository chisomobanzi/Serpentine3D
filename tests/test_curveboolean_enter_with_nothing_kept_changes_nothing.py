"""Enter with no region kept changes nothing and undoes cleanly.

Enter answers the pick, and a pick that kept nothing is a pick spent on
nothing: the command cancels rather than quietly eating the curves. All —
Alt+A — is the way to keep everything, so an empty Enter never has to mean
"everything".
"""

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def test_enter_right_away_cancels_and_leaves_the_curves(env):
    scene, selection, history, _ctx, proc = env
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    revision = scene.revision
    proc.run("curveboolean")
    assert proc.busy
    proc.provide_text("")            # Enter with nothing kept
    assert not proc.busy
    assert [o.id for o in scene.all() if o.kind == "curve"] == [a.id, b.id]
    assert selection.ids == []
    assert scene.revision == revision
    assert not history.can_undo, "a cancelled pass must not leave an undo step"
