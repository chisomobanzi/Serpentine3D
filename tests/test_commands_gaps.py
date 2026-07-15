"""Command-level tests for the daily-driver gap batch."""

import math

import pytest

import serpentine3d.commands  # registers commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
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


def test_point_command(env):
    scene, sel, hist, ctx, proc = env
    proc.run("point")
    proc.provide_text("1,2,3")
    proc.provide_text("4,5,6")
    proc.provide_text("")
    assert not proc.busy
    pts = [o for o in scene.all() if o.kind == "point"]
    assert len(pts) == 2
    assert g.point_coords(pts[0].shape) == pytest.approx((1, 2, 3))


def test_divide_command(env):
    scene, sel, hist, ctx, proc = env
    circle = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("divide")
    proc.click_object(circle.id)
    proc.finish_selection()
    proc.provide_text("4")
    pts = [o for o in scene.all() if o.kind == "point"]
    assert len(pts) == 4  # closed curve: no duplicate seam point


def test_divide_open_curve(env):
    scene, sel, hist, ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    proc.run("divide")
    proc.click_object(line.id)
    proc.finish_selection()
    proc.provide_text("4")
    pts = [o for o in scene.all() if o.kind == "point"]
    assert len(pts) == 5  # both ends included


def test_pipe_command(env):
    scene, sel, hist, ctx, proc = env
    rail = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    proc.run("pipe")
    proc.click_object(rail.id)
    proc.finish_selection()
    proc.provide_text("2")
    solids = [o for o in scene.all() if o.kind == "solid"]
    assert len(solids) == 1
    assert g.volume(solids[0].shape) == pytest.approx(math.pi * 4 * 10,
                                                      rel=1e-6)


def test_edgesrf_command(env):
    scene, sel, hist, ctx, proc = env
    ids = []
    for a, b in [((0, 0, 0), (10, 0, 0)), ((10, 0, 0), (10, 10, 0)),
                 ((10, 10, 0), (0, 10, 0)), ((0, 10, 0), (0, 0, 0))]:
        ids.append(scene.add(g.make_line(a, b)).id)
    proc.run("edgesrf")
    for i in ids:
        proc.click_object(i)
    proc.finish_selection()
    srfs = [o for o in scene.all() if o.kind == "surface"]
    assert len(srfs) == 1
    assert g.surface_area(srfs[0].shape) == pytest.approx(100, rel=1e-4)


def test_dupborder_command(env):
    scene, sel, hist, ctx, proc = env
    sheet = scene.add(g.extrude(g.make_line((0, 0, 0), (10, 0, 0)),
                                (0, 0, 1), 5.0))
    proc.run("dupborder")
    proc.click_object(sheet.id)
    proc.finish_selection()
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(30.0)


def test_dupedge_command(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    sel.subobjects.append((box.id, "edge", 0))
    proc.run("dupedge")
    assert not proc.busy
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(2.0)


def test_untrim_command(env):
    scene, sel, hist, ctx, proc = env
    disc = g.planar_face(g.make_circle((0, 0, 0), 5))
    small = g.planar_face(g.make_circle((0, 0, 0), 1))
    annulus = scene.add(g.boolean_difference(disc, small))
    proc.run("untrim")
    proc.click_object(annulus.id)
    proc.finish_selection()
    obj = scene.get(annulus.id)
    assert g.surface_area(obj.shape) == pytest.approx(math.pi * 25, rel=1e-4)


def test_extractisocurve_command(env):
    scene, sel, hist, ctx, proc = env
    cyl = scene.add(g.revolve(g.make_line((3, 0, 0), (3, 0, 10)),
                              (0, 0, 0), (0, 0, 1), 360))
    proc.run("extractisocurve")
    proc.click_object(cyl.id)
    proc.finish_selection()
    proc.provide_text("3,0,5")
    proc.provide_text("")
    assert not proc.busy
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(2 * math.pi * 3,
                                                            rel=1e-4)


def test_seldup_command(env):
    scene, sel, hist, ctx, proc = env
    box = g.make_box((0, 0, 0), 2, 2, 2)
    scene.add(box)
    dup = scene.add(g.copy_shape(box))
    scene.add(g.make_box((10, 0, 0), 1, 1, 1))
    proc.run("seldup")
    assert not proc.busy
    assert sel.ids == [dup.id]


def test_purge_command(env):
    scene, sel, hist, ctx, proc = env
    empty = scene.layers.create("Empty")
    used = scene.layers.create("Used")
    scene.add(g.make_line((0, 0, 0), (1, 0, 0)), layer_id=used.id)
    proc.run("purge")
    assert not proc.busy
    names = [la.name for la in scene.layers.all()]
    assert "Empty" not in names
    assert "Used" in names
    assert "Default" in names


def test_what_command(env):
    scene, sel, hist, ctx, proc = env
    msgs = []
    ctx.add_echo_listener(msgs.append)
    box = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    proc.run("what")
    proc.click_object(box.id)
    proc.finish_selection()
    text = "\n".join(msgs)
    assert "solid" in text
    assert "volume" in text
    assert "8" in text
