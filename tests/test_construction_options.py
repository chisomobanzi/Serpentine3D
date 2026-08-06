"""More than one way to say the same shape.

An arc is start, point on, end — unless what you know is the center and
the sweep, in which case those three picks are a puzzle about a shape you
could already describe. Rhino answers this with options on the first
prompt: type or click Center and the command asks for what you actually
know. These tests cover that pattern across the creation commands, and
the keywords are clickable chips as well as typed words.
"""

import math

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import (
    CommandContext, CommandProcessor, PointReq, format_prompt,
)
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
    proc = CommandProcessor(ctx)
    return scene, selection, history, ctx, proc


def _only(scene):
    objs = scene.all()
    assert len(objs) == 1
    return objs[0]


# -- the geometry itself --

def test_an_arc_swept_about_its_center():
    a = g.make_arc_center((0, 0, 0), (10, 0, 0), math.pi / 2, (0, 0, 1))
    assert g.curve_length(a) == pytest.approx(math.pi * 5, rel=1e-6)
    mn, mx = g.bbox(a)
    assert mx[0] == pytest.approx(10, abs=1e-6)
    assert mx[1] == pytest.approx(10, abs=1e-6)
    assert mn[1] == pytest.approx(0, abs=1e-6)


def test_a_negative_angle_sweeps_the_other_way():
    a = g.make_arc_center((0, 0, 0), (10, 0, 0), -math.pi / 2, (0, 0, 1))
    mn, _mx = g.bbox(a)
    assert mn[1] == pytest.approx(-10, abs=1e-6)
    assert g.curve_length(a) == pytest.approx(math.pi * 5, rel=1e-6)


def test_a_full_turn_is_not_an_arc():
    with pytest.raises(g.GeometryError):
        g.make_arc_center((0, 0, 0), (10, 0, 0), 2 * math.pi, (0, 0, 1))
    with pytest.raises(g.GeometryError):
        g.make_arc_center((0, 0, 0), (10, 0, 0), 0.0, (0, 0, 1))
    with pytest.raises(g.GeometryError):
        g.make_arc_center((0, 0, 0), (0, 0, 0), 1.0, (0, 0, 1))


def test_a_circle_through_three_points():
    c = g.make_circle_3pt((10, 0, 0), (0, 10, 0), (-10, 0, 0))
    assert g.curve_length(c) == pytest.approx(2 * math.pi * 10, rel=1e-6)
    mn, mx = g.bbox(c)
    assert mn[0] == pytest.approx(-10, abs=1e-6)
    assert mx[1] == pytest.approx(10, abs=1e-6)


def test_three_points_in_a_row_make_no_circle():
    with pytest.raises(g.GeometryError):
        g.make_circle_3pt((0, 0, 0), (5, 0, 0), (10, 0, 0))


def test_an_ellipse_on_a_tilted_axis():
    s = math.sqrt(0.5)
    e = g.make_ellipse_axis((0, 0, 0), (s, s, 0), 10, 4, (0, 0, 1))
    # the long way runs along the diagonal, so the world bbox is square-ish
    # rather than 20 x 8, and the curve passes through the axis end
    pts = g.sample_curve(e, 400)
    end = (10 * s, 10 * s, 0.0)
    assert min(math.dist(p, end) for p in pts) < 0.05


def test_the_first_axis_keeps_its_direction_when_it_is_the_short_one():
    # gp_Elips insists major >= minor; the helper must not let that swap
    # which way the named axis points
    e = g.make_ellipse_axis((0, 0, 0), (1, 0, 0), 3, 8, (0, 0, 1))
    pts = g.sample_curve(e, 400)
    assert min(math.dist(p, (3, 0, 0)) for p in pts) < 0.05
    assert min(math.dist(p, (0, 8, 0)) for p in pts) < 0.05


# -- arc --

def test_arc_by_center_start_end(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    proc.provide_text("center")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("0,10,0")
    assert not proc.busy
    arc = _only(scene)
    assert g.curve_length(arc.shape) == pytest.approx(math.pi * 5, rel=1e-6)


def test_arc_by_center_takes_a_typed_angle(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc center")            # macro form works too
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("90")
    arc = _only(scene)
    assert g.curve_length(arc.shape) == pytest.approx(math.pi * 5, rel=1e-6)
    _mn, mx = g.bbox(arc.shape)
    assert mx[1] == pytest.approx(10, abs=1e-6)


def test_arc_by_center_takes_a_negative_angle(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc center")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("-90")
    arc = _only(scene)
    mn, _mx = g.bbox(arc.shape)
    assert mn[1] == pytest.approx(-10, abs=1e-6)


def test_arc_by_center_pulls_the_end_onto_the_circle(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc center")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("0,25,0")       # off the circle: direction, not radius
    arc = _only(scene)
    assert g.curve_length(arc.shape) == pytest.approx(math.pi * 5, rel=1e-6)


def test_arc_by_start_end_and_a_point_on_it(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    proc.provide_text("startend")
    proc.provide_text("10,0,0")
    proc.provide_text("-10,0,0")
    proc.provide_text("0,10,0")
    arc = _only(scene)
    assert g.curve_length(arc.shape) == pytest.approx(math.pi * 10, rel=1e-6)


def test_arc_three_points_still_the_default(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    proc.provide_text("10,0,0")
    proc.provide_text("0,10,0")
    proc.provide_text("-10,0,0")
    arc = _only(scene)
    assert g.curve_length(arc.shape) == pytest.approx(math.pi * 10, rel=1e-6)


# -- circle --

def test_circle_by_two_ends_of_a_diameter(env):
    scene, sel, hist, ctx, proc = env
    proc.run("circle")
    proc.provide_text("2point")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    c = _only(scene)
    assert g.curve_length(c.shape) == pytest.approx(2 * math.pi * 5, rel=1e-6)
    mn, mx = g.bbox(c.shape)
    assert mn[0] == pytest.approx(0, abs=1e-6)
    assert mx[0] == pytest.approx(10, abs=1e-6)


def test_circle_through_three_points(env):
    scene, sel, hist, ctx, proc = env
    proc.run("circle")
    proc.provide_text("3point")
    proc.provide_text("10,0,0")
    proc.provide_text("0,10,0")
    proc.provide_text("-10,0,0")
    c = _only(scene)
    assert g.curve_length(c.shape) == pytest.approx(2 * math.pi * 10, rel=1e-6)


def test_circle_takes_a_typed_diameter(env):
    scene, sel, hist, ctx, proc = env
    proc.run("circle")
    proc.provide_text("0,0,0")
    proc.provide_text("diameter")
    proc.provide_text("10")
    c = _only(scene)
    assert g.curve_length(c.shape) == pytest.approx(math.pi * 10, rel=1e-6)


# -- line, curve --

def test_line_from_the_middle_out(env):
    scene, sel, hist, ctx, proc = env
    proc.run("line")
    proc.provide_text("bothsides")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    ln = _only(scene)
    assert g.curve_length(ln.shape) == pytest.approx(20)
    mn, _mx = g.bbox(ln.shape)
    assert mn[0] == pytest.approx(-10, abs=1e-6)


def test_a_curve_can_close_back_on_itself(env):
    scene, sel, hist, ctx, proc = env
    proc.run("curve")
    for t in ("0,0", "10,0", "10,10", "0,10"):
        proc.provide_text(t)
    proc.provide_text("close")
    c = _only(scene)
    assert g.is_closed_curve(c.shape)


# -- rectangle --

def test_rectangle_from_its_center(env):
    scene, sel, hist, ctx, proc = env
    proc.run("rectangle")
    proc.provide_text("center")
    proc.provide_text("0,0,0")
    proc.provide_text("5,3,0")
    r = _only(scene)
    mn, mx = g.bbox(r.shape)
    assert mn[0] == pytest.approx(-5, abs=1e-6)
    assert mn[1] == pytest.approx(-3, abs=1e-6)
    assert mx[0] == pytest.approx(5, abs=1e-6)
    assert mx[1] == pytest.approx(3, abs=1e-6)


def test_rectangle_from_its_center_by_typed_sides(env):
    scene, sel, hist, ctx, proc = env
    proc.run("rectangle")
    proc.provide_text("center")
    proc.provide_text("0,0,0")
    proc.provide_text("10")
    proc.provide_text("6")
    r = _only(scene)
    mn, mx = g.bbox(r.shape)
    assert (mx[0] - mn[0]) == pytest.approx(10, abs=1e-6)
    assert (mx[1] - mn[1]) == pytest.approx(6, abs=1e-6)
    assert (mx[0] + mn[0]) == pytest.approx(0, abs=1e-6)


def test_rectangle_by_an_edge_and_a_width(env):
    scene, sel, hist, ctx, proc = env
    proc.run("rectangle")
    proc.provide_text("3point")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("5,4,0")
    r = _only(scene)
    mn, mx = g.bbox(r.shape)
    assert mn == pytest.approx((0, 0, 0), abs=1e-6)
    assert mx == pytest.approx((10, 4, 0), abs=1e-6)


def test_rectangle_by_an_edge_hangs_on_the_side_you_point(env):
    scene, sel, hist, ctx, proc = env
    proc.run("rectangle 3point")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("5,-4,0")
    r = _only(scene)
    mn, mx = g.bbox(r.shape)
    assert mn[1] == pytest.approx(-4, abs=1e-6)
    assert mx[1] == pytest.approx(0, abs=1e-6)


def test_rectangle_by_a_tilted_edge(env):
    scene, sel, hist, ctx, proc = env
    proc.run("rectangle 3point")
    proc.provide_text("0,0,0")
    proc.provide_text("10,10,0")
    proc.provide_text("0,10,0")
    r = _only(scene)
    # edge (0,0)->(10,10) is sqrt(200) long; (0,10) sits sqrt(50) off it
    assert g.curve_length(r.shape) == pytest.approx(
        2 * math.sqrt(200) + 2 * math.sqrt(50), rel=1e-6)
    # the corners are off-axis, so check one of them by name
    pts = [tuple(p) for p in g.get_control_points(r.shape)]
    assert any(math.dist(p, (10, 10, 0)) < 1e-6 for p in pts)


# -- box, sphere --

def test_box_from_the_center_of_its_base(env):
    scene, sel, hist, ctx, proc = env
    proc.run("box")
    proc.provide_text("center")
    proc.provide_text("0,0,0")
    proc.provide_text("5,4,0")
    proc.provide_text("10")
    b = _only(scene)
    assert g.volume(b.shape) == pytest.approx(10 * 8 * 10, rel=1e-6)
    mn, mx = g.bbox(b.shape)
    assert mn[0] == pytest.approx(-5, abs=1e-4)
    assert mx[2] == pytest.approx(10, abs=1e-4)


def test_sphere_by_two_ends_of_a_diameter(env):
    scene, sel, hist, ctx, proc = env
    proc.run("sphere")
    proc.provide_text("2point")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    s = _only(scene)
    assert g.volume(s.shape) == pytest.approx(4 / 3 * math.pi * 125,
                                              rel=1e-4)
    mn, mx = g.bbox(s.shape)
    assert mn[0] == pytest.approx(0, abs=1e-4)
    assert mx[0] == pytest.approx(10, abs=1e-4)


# -- ellipse --

def test_ellipse_by_the_ends_of_its_first_axis(env):
    scene, sel, hist, ctx, proc = env
    proc.run("ellipse")
    proc.provide_text("diameter")
    proc.provide_text("-10,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("0,4,0")
    e = _only(scene)
    mn, mx = g.bbox(e.shape)
    assert mn[0] == pytest.approx(-10, abs=1e-4)
    assert mx[1] == pytest.approx(4, abs=1e-4)


def test_ellipse_axis_ends_need_not_lie_on_an_axis(env):
    scene, sel, hist, ctx, proc = env
    proc.run("ellipse diameter")
    proc.provide_text("0,0,0")
    proc.provide_text("10,10,0")
    proc.provide_text("4,6,0")        # off the axis: sets the half-width
    e = _only(scene)
    pts = g.sample_curve(e.shape, 400)
    assert min(math.dist(p, (10, 10, 0)) for p in pts) < 0.05
    assert min(math.dist(p, (0, 0, 0)) for p in pts) < 0.05


# -- the words are discoverable --

def test_the_prompt_names_the_other_ways(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    assert "Center" in proc.prompt_text()
    assert "StartEnd" in proc.prompt_text()
    proc.cancel()
    proc.run("circle")
    assert "2Point" in proc.prompt_text()


def test_the_keywords_come_as_chips(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    assert proc.keyword_chips() == ["Center", "StartEnd"]
    proc.cancel()
    proc.run("polyline")
    proc.provide_text("0,0")
    proc.provide_text("10,0")
    proc.provide_text("10,10")
    assert "Close" in proc.keyword_chips()
    proc.cancel()
    assert proc.keyword_chips() == []


def test_a_prefix_of_a_keyword_is_enough(env):
    scene, sel, hist, ctx, proc = env
    proc.run("arc")
    proc.provide_text("cen")
    assert isinstance(proc.request, PointReq)
    assert "Center of arc" in proc.prompt_text()


def test_format_prompt_shows_extra_options():
    req = PointReq("Start of arc", extra_options=("Center", "StartEnd"))
    assert format_prompt(req) == "Start of arc (Center/StartEnd)"


def test_clicking_a_keyword_chip_answers_the_prompt(env, qapp):
    scene, sel, hist, ctx, proc = env
    from serpentine3d.ui.command_line import CommandLine
    cl = CommandLine()
    heard = []
    cl.keywordClicked.connect(heard.append)
    cl.set_keywords(["Center", "StartEnd"])
    assert [b.text() for b in cl._keyword_chips] == ["Center", "StartEnd"]
    cl._keyword_chips[0].click()
    assert heard == ["Center"]
    cl.set_keywords([])
    assert cl._keyword_chips == []
    cl.deleteLater()


@pytest.fixture
def qapp(_qapp):
    return _qapp
