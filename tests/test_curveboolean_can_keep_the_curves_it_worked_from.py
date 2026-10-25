"""CurveBoolean can leave the curves it worked from where they were.

It has always consumed them, which is what you want when the boolean is
the drawing. It is not what you want when the same outlines are about to
be booleaned another way, or are the construction the rest of the drawing
is set out from, so KeepObjects offers the other answer, the way Rhino's
commands offer DeleteInput. The default is the behaviour it always had.
"""

import pytest

from serpentine3d.core import geometry as g


def _circle(scene, x, y, r):
    return scene.add(g.make_circle((x, y, 0.0), r))


def _two_circles(scene, selection):
    a = _circle(scene, 0.0, 0.0, 2.0)
    b = _circle(scene, 2.0, 0.0, 2.0)
    selection.set([a.id, b.id])
    return a, b


def test_the_curves_are_consumed_unless_you_say_otherwise(env):
    scene, selection, _history, _ctx, proc = env
    a, b = _two_circles(scene, selection)

    proc.run("curveboolean")
    proc.provide((1.0, 0.0, 0.0))
    proc.provide_text("")

    assert scene.get(a.id) is None and scene.get(b.id) is None


def test_keepobjects_leaves_them_where_they_were(env):
    scene, selection, _history, _ctx, proc = env
    a, b = _two_circles(scene, selection)

    proc.run("curveboolean")
    proc.provide_text("KeepObjects")
    proc.provide((1.0, 0.0, 0.0))
    proc.provide_text("")

    assert scene.get(a.id) is not None and scene.get(b.id) is not None
    made = [o for o in scene.all() if o.kind == "curve"
            and o.id not in (a.id, b.id)]
    assert len(made) == 1, "the boolean still made its outline"


def test_what_it_made_is_what_is_selected_either_way(env):
    scene, selection, _history, _ctx, proc = env
    a, b = _two_circles(scene, selection)

    proc.run("curveboolean")
    proc.provide_text("KeepObjects")
    proc.provide((1.0, 0.0, 0.0))
    proc.provide_text("")

    made = [o for o in scene.all() if o.id not in (a.id, b.id)]
    assert selection.ids == [made[0].id]


def test_undo_puts_the_drawing_back_with_the_option_on(env):
    scene, selection, history, _ctx, proc = env
    a, b = _two_circles(scene, selection)

    proc.run("curveboolean")
    proc.provide_text("KeepObjects")
    proc.provide((1.0, 0.0, 0.0))
    proc.provide_text("")
    history.undo()

    assert [o.id for o in scene.all()] == [a.id, b.id]


def test_the_option_is_offered_on_the_pick(env):
    scene, selection, _history, _ctx, proc = env
    _two_circles(scene, selection)

    proc.run("curveboolean")

    offered = proc.request.choices or {}
    assert "KeepObjects" in offered
    assert offered["KeepObjects"][0] == "No", "the default is what it did"
