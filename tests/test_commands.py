import pytest

import serpentine.commands  # registers all commands  # noqa: F401
from serpentine.commands.base import (
    CommandContext, CommandProcessor, PointReq, SelectReq, parse_point,
    resolve,
)
from serpentine.core import geometry as g
from serpentine.core.history import History
from serpentine.core.scene import Scene
from serpentine.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    return scene, selection, history, ctx, proc


def test_parse_point():
    assert parse_point("1,2,3") == (1, 2, 3)
    assert parse_point("1,2") == (1, 2, 0)
    assert parse_point(" 1.5 , -2 ") == (1.5, -2, 0)
    assert parse_point("@1,0,0", (5, 5, 5)) == (6, 5, 5)
    assert parse_point("nonsense") is None


def test_registry_aliases():
    assert resolve("line").name == "line"
    assert resolve("L").name == "line"
    assert resolve("ze").name == "zoomextents"
    assert resolve("nope") is None


def test_line_command(env):
    scene, sel, hist, ctx, proc = env
    proc.run("line")
    assert isinstance(proc.request, PointReq)
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    assert not proc.busy
    assert len(scene.all()) == 1
    assert g.curve_length(scene.all()[0].shape) == pytest.approx(10)


def test_relative_coordinates(env):
    scene, sel, hist, ctx, proc = env
    proc.run("line")
    proc.provide_text("5,5,0")
    proc.provide_text("@10,0,0")
    obj = scene.all()[0]
    mn, mx = g.bbox(obj.shape)
    assert mx[0] == pytest.approx(15, abs=1e-6)


def test_polyline_close(env):
    scene, sel, hist, ctx, proc = env
    proc.run("polyline")
    for t in ("0,0", "10,0", "10,10", "0,10"):
        proc.provide_text(t)
    proc.provide_text("c")           # close
    assert not proc.busy
    assert g.is_closed_curve(scene.all()[0].shape)


def test_circle_and_extrude_via_selection(env):
    scene, sel, hist, ctx, proc = env
    proc.run("circle")
    proc.provide_text("0,0,0")
    proc.provide_text("5")
    assert len(scene.all()) == 1

    proc.run("extrude")
    assert isinstance(proc.request, SelectReq)
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()
    proc.provide_text("10")          # distance
    proc.provide_text("")            # cap default Yes
    assert not proc.busy
    solids = [o for o in scene.all() if o.kind == "solid"]
    assert len(solids) == 1
    import math
    assert g.volume(solids[0].shape) == pytest.approx(
        math.pi * 25 * 10, rel=1e-3)


def test_preselection_skips_select_request(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_circle((0, 0, 0), 3))
    sel.set([obj.id])
    proc.run("extrude")
    # selection consumed automatically; first prompt is the distance
    from serpentine.commands.base import NumberReq
    assert isinstance(proc.request, NumberReq)


def test_cancel_restores_scene(env):
    scene, sel, hist, ctx, proc = env
    proc.run("line")
    proc.provide_text("0,0,0")
    proc.cancel()
    assert not proc.busy
    assert len(scene.all()) == 0
    assert not hist.can_undo        # cancelled command leaves no undo entry


def test_undo_after_command(env):
    scene, sel, hist, ctx, proc = env
    proc.run("line")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    assert hist.can_undo
    proc.run("undo")
    assert len(scene.all()) == 0
    proc.run("redo")
    assert len(scene.all()) == 1


def test_move_command(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("move")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("5,5,0")
    mn, mx = g.bbox(scene.all()[0].shape)
    assert mn[0] == pytest.approx(5, abs=1e-6)


def test_copy_command_multiple(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("copy")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("5,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("")           # finish
    assert len(scene.all()) == 3


def test_rotate_scale_mirror(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_box((1, 0, 0), 1, 1, 1))

    proc.run("rotate")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("90")
    mn, mx = g.bbox(scene.all()[0].shape)
    assert mx[1] == pytest.approx(2, abs=1e-6)

    proc.run("scale")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("2")
    assert g.volume(scene.all()[0].shape) == pytest.approx(8, rel=1e-5)

    proc.run("mirror")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("0,10,0")     # mirror across YZ-ish plane (x -> -x)
    proc.provide_text("")           # keep original: Yes
    assert len(scene.all()) == 2


def test_boolean_union_difference(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    b = scene.add(g.make_box((5, 5, 5), 10, 10, 10))

    proc.run("booleanunion")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.finish_selection()
    assert len(scene.all()) == 1
    assert g.volume(scene.all()[0].shape) == pytest.approx(1875)

    proc.run("undo")
    assert len(scene.all()) == 2

    proc.run("booleandifference")
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()
    proc.click_object(scene.all()[1].id)
    proc.finish_selection()
    assert len(scene.all()) == 1
    assert g.volume(scene.all()[0].shape) == pytest.approx(875)


def test_loft_command(env):
    scene, sel, hist, ctx, proc = env
    c1 = scene.add(g.make_circle((0, 0, 0), 5))
    c2 = scene.add(g.make_circle((0, 0, 10), 3))
    proc.run("loft")
    proc.click_object(c1.id)
    proc.click_object(c2.id)
    proc.finish_selection()
    proc.provide_text("")           # style default
    kinds = [o.kind for o in scene.all()]
    assert "surface" in kinds or "solid" in kinds


def test_delete_and_join(env):
    scene, sel, hist, ctx, proc = env
    l1 = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    l2 = scene.add(g.make_line((10, 0, 0), (10, 10, 0)))
    proc.run("join")
    proc.click_object(l1.id)
    proc.click_object(l2.id)
    proc.finish_selection()
    assert len(scene.all()) == 1
    assert g.curve_length(scene.all()[0].shape) == pytest.approx(20)

    proc.run("delete")
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()
    assert len(scene.all()) == 0


def test_layer_command(env):
    scene, sel, hist, ctx, proc = env
    proc.run("layer")
    proc.provide_text("New")
    proc.provide_text("Walls")
    layer = scene.layers.find_by_name("Walls")
    assert layer is not None
    assert scene.layers.current_id == layer.id


def test_unknown_command_reports(env):
    scene, sel, hist, ctx, proc = env
    msgs = []
    ctx.add_echo_listener(msgs.append)
    assert proc.run("frobnicate") is False
    assert any("Unknown command" in m for m in msgs)


def test_select_by_name_and_all(env):
    scene, sel, hist, ctx, proc = env
    scene.add(g.make_line((0, 0, 0), (1, 0, 0)), name="Alpha")
    scene.add(g.make_line((0, 0, 0), (2, 0, 0)), name="Beta")
    proc.run("delete")
    proc.provide_text("Alpha")
    proc.finish_selection()
    assert len(scene.all()) == 1
    assert scene.all()[0].name == "Beta"
