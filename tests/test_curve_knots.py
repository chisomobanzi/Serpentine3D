"""Knots — the seams inside a NURBS curve, and editing through them.

Rhino's InsertKnot, RemoveKnot and InsertControlPoint. Inserting a knot is
the one edit that hands you a new control point without moving the curve at
all, so it is how you get a handle where you want to pull from rather than
where the curve happens to already have one. Removing one is the opposite
trade: a span fewer, and the curve gives up whatever that knot was holding.
"""

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor, resolve
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    return scene, selection, history, ctx, CommandProcessor(ctx)


def _wiggle():
    """Degree 3, five poles: one interior knot, so there is both somewhere
    to put a knot and something to take out."""
    return g.make_control_curve(
        [(0, 0, 0), (10, 10, 0), (20, -10, 0), (30, 10, 0), (40, 0, 0)],
        degree=3)


def _on_the_curve(shape, i=3, n=9):
    """A point that really is on the curve, so a pick can be aimed at it."""
    return g.sample_curve(shape, n)[i]


def _d3(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _same_shape(a, b, n=40, tol=1e-7):
    return all(pa == pytest.approx(pb, abs=tol)
               for pa, pb in zip(g.sample_curve(a, n), g.sample_curve(b, n)))


# --- inserting -------------------------------------------------------------

def test_a_new_knot_adds_a_control_point():
    c = _wiggle()
    assert len(g.get_control_points(g.insert_knot(c, _on_the_curve(c)))) == \
        len(g.get_control_points(c)) + 1


def test_a_new_knot_leaves_the_curve_exactly_where_it_was():
    """The whole point of inserting a knot rather than rebuilding: you get
    somewhere to pull from and pay nothing for it."""
    c = _wiggle()
    assert _same_shape(c, g.insert_knot(c, _on_the_curve(c)))


def test_the_knot_lands_where_you_pointed():
    c = _wiggle()
    p = _on_the_curve(c)
    knots = g.curve_knot_points(g.insert_knot(c, p))
    assert min(_d3(p, k) for k in knots) < 1e-6, (
        f"no knot near the pick {p}, got {knots}")


def test_a_pick_beside_the_curve_still_lands_on_it():
    """You aim at a curve, you do not hit it. The knot goes to the nearest
    place on the curve, which is what you meant."""
    c = _wiggle()                       # flat in z=0, so straight up
    p = _on_the_curve(c)                # projects back onto itself
    knots = g.curve_knot_points(g.insert_knot(c, (p[0], p[1], p[2] + 7)))
    assert min(_d3(p, k) for k in knots) < 1e-6


def test_an_automatic_pass_puts_a_knot_in_every_span():
    c = _wiggle()
    before = len(g.curve_knot_points(c))
    after = len(g.curve_knot_points(g.insert_knots_at_spans(c)))
    assert after == 2 * before + 1, "each of the spans should have gained one"


def test_an_automatic_pass_also_leaves_the_curve_alone():
    c = _wiggle()
    assert _same_shape(c, g.insert_knots_at_spans(c))


def test_a_polyline_gains_a_corner_where_you_click():
    """A polyline is degree 1, so its knots are its corners and a new one is
    a new corner sitting exactly on the segment it splits."""
    pl = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    out = g.insert_knot(pl, (5, 0, 0))
    pts = g.get_control_points(out)
    assert len(pts) == 4
    assert min(_d3((5, 0, 0), p) for p in pts) < 1e-9
    assert _same_shape(pl, out)


def test_a_closed_curve_can_take_a_knot_too():
    c = g.make_control_curve([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)],
                             degree=3, closed=True)
    out = g.insert_knot(c, _on_the_curve(c))
    assert len(g.get_control_points(out)) == len(g.get_control_points(c)) + 1
    assert g.is_closed_curve(out)


# --- removing --------------------------------------------------------------

def test_removing_the_knot_you_just_added_gives_the_curve_back():
    c = _wiggle()
    p = _on_the_curve(c)
    back = g.remove_knot(g.insert_knot(c, p), p)
    assert len(g.get_control_points(back)) == len(g.get_control_points(c))
    assert _same_shape(c, back, tol=1e-6)


def test_removing_a_knot_takes_a_control_point_with_it():
    c = _wiggle()
    out = g.remove_knot(c, _on_the_curve(c))
    assert len(g.get_control_points(out)) == len(g.get_control_points(c)) - 1


def test_a_curve_of_one_span_has_no_knot_to_remove():
    """Its only knots are the two holding it onto its end poles, and taking
    one of those out is not an edit, it is a broken curve."""
    c = g.make_control_curve([(0, 0, 0), (10, 10, 0), (20, -10, 0),
                              (30, 0, 0)], degree=3)
    assert g.curve_knot_points(c) == []
    with pytest.raises(g.GeometryError, match="knot"):
        g.remove_knot(c, _on_the_curve(c))


def test_the_knot_nearest_the_pick_is_the_one_that_goes():
    c = g.make_control_curve(
        [(0, 0, 0), (10, 10, 0), (20, -10, 0), (30, 10, 0), (40, -10, 0),
         (50, 10, 0), (60, 0, 0)], degree=3)
    knots = g.curve_knot_points(c)
    assert len(knots) >= 3
    doomed = knots[1]
    left = g.curve_knot_points(g.remove_knot(c, doomed))
    assert min(_d3(doomed, k) for k in left) > 1e-6, "wrong knot removed"
    assert len(left) == len(knots) - 1


# --- the commands ----------------------------------------------------------

def test_insertknot_answers_to_rhinos_names():
    assert resolve("insertknot").name == "insertknot"
    assert resolve("insertcontrolpoint").name == "insertknot"
    assert resolve("removeknot").name == "removeknot"


def _pick(env, cmd, obj, *points):
    _scene, sel, _hist, _ctx, proc = env
    sel.set([obj.id] if not isinstance(obj, list) else [o.id for o in obj])
    proc.run(cmd)
    for p in points:
        proc.provide(tuple(float(c) for c in p))
    proc.provide(None)
    return proc


def test_insertknot_adds_a_point_to_the_curve(env):
    scene, _sel, _hist, _ctx, _proc = env
    obj = scene.add(_wiggle())
    before = len(g.get_control_points(obj.shape))
    _pick(env, "insertknot", obj, _on_the_curve(obj.shape))
    assert len(g.get_control_points(scene.get(obj.id).shape)) == before + 1


def test_insertknot_keeps_taking_points_until_you_press_enter(env):
    scene, _sel, _hist, _ctx, _proc = env
    obj = scene.add(_wiggle())
    before = len(g.get_control_points(obj.shape))
    _pick(env, "insertknot", obj,
          _on_the_curve(obj.shape, 2), _on_the_curve(obj.shape, 6))
    assert len(g.get_control_points(scene.get(obj.id).shape)) == before + 2


def test_the_click_says_which_of_the_selected_curves_you_meant(env):
    """Both are picked, but a knot goes where you pointed, not everywhere."""
    scene, _sel, _hist, _ctx, _proc = env
    near = scene.add(_wiggle())
    far = scene.add(g.make_control_curve(
        [(0, 500, 0), (10, 510, 0), (20, 490, 0), (30, 500, 0),
         (40, 500, 0)], degree=3))
    n_far = len(g.get_control_points(far.shape))
    n_near = len(g.get_control_points(near.shape))
    _pick(env, "insertknot", [near, far], _on_the_curve(near.shape))
    assert len(g.get_control_points(scene.get(near.id).shape)) == n_near + 1
    assert len(g.get_control_points(scene.get(far.id).shape)) == n_far


def test_insertknot_shows_the_control_polygon_you_would_get(env):
    """The curve does not move, so ghosting the curve would show nothing.
    What changes is the polygon, and where the new handle sits in it."""
    _scene, sel, _hist, _ctx, proc = env
    scene = _scene
    obj = scene.add(_wiggle())
    sel.set([obj.id])
    proc.run("insertknot")
    p = _on_the_curve(obj.shape)
    ghost = proc.preview_for(p)
    assert ghost is not None, "nothing under the cursor while inserting a knot"
    poles = g.get_control_points(ghost)
    assert len(poles) == len(g.get_control_points(obj.shape)) + 1
    for got, want in zip(poles, g.get_control_points(
            g.insert_knot(obj.shape, p))):
        assert got == pytest.approx(want, abs=1e-9)


def test_removeknot_takes_out_the_knot_you_click_near(env):
    scene, _sel, _hist, _ctx, _proc = env
    obj = scene.add(_wiggle())
    before = len(g.get_control_points(obj.shape))
    _pick(env, "removeknot", obj, g.curve_knot_points(obj.shape)[0])
    assert len(g.get_control_points(scene.get(obj.id).shape)) == before - 1


def test_removeknot_shows_the_curve_you_would_be_left_with(env):
    """This one does move the curve, so the curve is the honest preview."""
    scene, sel, _hist, _ctx, proc = env
    obj = scene.add(_wiggle())
    sel.set([obj.id])
    proc.run("removeknot")
    ghost = proc.preview_for(g.curve_knot_points(obj.shape)[0])
    assert ghost is not None
    assert len(g.get_control_points(ghost)) == \
        len(g.get_control_points(obj.shape)) - 1


def test_a_curve_with_nothing_to_remove_says_so_and_carries_on(env):
    scene, _sel, _hist, ctx, _proc = env
    msgs: list = []
    ctx.add_echo_listener(msgs.append)
    obj = scene.add(g.make_control_curve(
        [(0, 0, 0), (10, 10, 0), (20, -10, 0), (30, 0, 0)], degree=3))
    proc = _pick(env, "removeknot", obj, _on_the_curve(obj.shape))
    assert not proc.busy
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 4
    assert any("no knots" in m.lower() for m in msgs), (
        f"the command should say why nothing happened, said {msgs}")
