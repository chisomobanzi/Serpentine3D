import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import (
    CommandContext, CommandProcessor, PointReq, SelectReq, parse_point,
    resolve,
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
    from serpentine3d.commands.base import NumberReq
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


def test_split_command(env):
    scene, sel, hist, ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    cutter = scene.add(g.make_line((5, -5, 0), (5, 5, 0)))
    proc.run("split")
    proc.click_object(line.id)
    proc.click_object(cutter.id)
    proc.finish_selection()
    curves = [o for o in scene.all() if o.id != cutter.id]
    assert len(curves) == 2


def test_trim_command(env):
    scene, sel, hist, ctx, proc = env
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="Target")
    cutter = scene.add(g.make_line((5, -5, 0), (5, 5, 0)), name="Cutter")
    proc.run("trim")
    proc.click_object(cutter.id)
    proc.finish_selection()
    proc.click_object(line.id)
    # pieces now exist; remove the shorter/left piece by name lookup
    pieces = [o for o in scene.all() if o.id not in (cutter.id,)]
    assert len(pieces) == 2
    proc.click_object(pieces[0].id)
    proc.finish_selection()
    remaining = [o for o in scene.all() if o.id != cutter.id]
    assert len(remaining) == 1
    assert g.curve_length(remaining[0].shape) == pytest.approx(5)


def test_sweep2_command(env):
    scene, sel, hist, ctx, proc = env
    r1 = scene.add(g.make_line((0, 0, 0), (20, 0, 0)))
    r2 = scene.add(g.make_line((0, 5, 0), (20, 5, 0)))
    prof = scene.add(g.make_line((0, 0, 0), (0, 0, 3)))
    proc.run("sweep2")
    proc.click_object(r1.id)
    proc.click_object(r2.id)
    proc.click_object(prof.id)
    assert any(o.kind in ("surface", "solid") for o in scene.all())


def test_selection_filter_commands(env):
    scene, sel, hist, ctx, proc = env
    scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    srf = scene.add(g.planar_face(g.make_circle((5, 5, 0), 2)))
    proc.run("selcrv")
    assert len(sel.ids) == 1
    proc.run("selsolid")
    assert len(sel.ids) == 1
    proc.run("selsrf")
    assert sel.ids == [srf.id]
    proc.run("invert")
    assert len(sel.ids) == 2
    proc.run("sellast")
    assert sel.ids == [srf.id]


def test_isolate_unisolate(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    b = scene.add(g.make_box((5, 0, 0), 1, 1, 1))
    c = scene.add(g.make_box((10, 0, 0), 1, 1, 1))
    proc.run("isolate")
    proc.click_object(a.id)
    proc.finish_selection()
    assert len(scene.visible_objects()) == 1
    proc.run("unisolate")
    assert len(scene.visible_objects()) == 3


def test_sellayer_and_selname(env):
    scene, sel, hist, ctx, proc = env
    layer = scene.layers.create("Props")
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="Crate A",
              layer_id=layer.id)
    scene.add(g.make_box((3, 0, 0), 1, 1, 1), name="Crate B")
    proc.run("sellayer")
    proc.provide_text("Props")
    assert len(sel.ids) == 1
    proc.run("selname")
    proc.provide_text("crate")
    assert len(sel.ids) == 2


def test_feet_inches_input(env):
    scene, sel, hist, ctx, proc = env
    scene.units = "ft"
    proc.run("circle")
    proc.provide_text("0,0,0")
    proc.provide_text("3'6\"")           # radius = 3.5 ft
    import math
    assert g.curve_length(scene.all()[0].shape) == pytest.approx(
        2 * math.pi * 3.5, rel=1e-6)
    # coordinates with units + polar input
    proc.run("line")
    proc.provide_text("1',2',0")
    proc.provide_text("10<0")            # 10 ft along +X
    mn, mx = g.bbox(scene.all()[1].shape)
    assert mn[0] == pytest.approx(1) and mx[0] == pytest.approx(11)
    assert mn[1] == pytest.approx(2)


def test_units_command_rescale(env):
    scene, sel, hist, ctx, proc = env
    scene.add(g.make_box((0, 0, 0), 1000, 1000, 1000))   # 1m box in mm
    proc.run("units")
    proc.provide_text("m")
    proc.provide_text("Yes")             # rescale
    assert scene.units == "m"
    assert g.volume(scene.all()[0].shape) == pytest.approx(1.0, rel=1e-6)
    proc.run("undo")
    assert g.volume(scene.all()[0].shape) == pytest.approx(1e9, rel=1e-6)


def test_filletedge_and_contour_commands(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 30))
    proc.run("filletedge")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("1")
    assert 2800 < g.volume(scene.all()[0].shape) < 3000

    proc.run("contour")
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()
    proc.provide_text("Z")
    proc.provide_text("10")
    contours = [o for o in scene.all() if o.kind == "curve"]
    assert len(contours) >= 2
    assert scene.layers.find_by_name("Contours") is not None


def test_intersect_command(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    b = scene.add(g.make_sphere((10, 5, 5), 3))
    proc.run("intersect")
    proc.click_object(a.id)
    proc.click_object(b.id)
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) >= 1


def test_booleansplit_command(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    line = g.make_line((5, -1, -1), (5, 11, -1))
    cutter = scene.add(g.extrude(g.make_line((5, -5, -5), (5, 15, -5)),
                                 (0, 0, 1), 25))
    proc.run("booleansplit")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.click_object(cutter.id)
    proc.finish_selection()
    solids = [o for o in scene.all() if o.kind == "solid"]
    assert len(solids) == 2
    for s in solids:
        assert g.volume(s.shape) == pytest.approx(500, rel=1e-6)


def test_group_lock_block(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="A")
    b = scene.add(g.make_box((3, 0, 0), 1, 1, 1), name="B")
    c = scene.add(g.make_box((6, 0, 0), 1, 1, 1), name="C")

    # group A+B: expansion picks up both
    proc.run("group")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.finish_selection()
    expanded = scene.expand_group_ids([a.id])
    assert set(expanded) == {a.id, b.id}

    # lock C: unselectable, filters skip it
    proc.run("lock")
    proc.click_object(c.id)
    proc.finish_selection()
    assert not scene.is_selectable(c.id)
    sel.select_all()
    assert c.id not in sel.ids
    proc.run("unlockall")
    assert scene.is_selectable(c.id)

    # block from A+B, then insert a second instance
    proc.run("block")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.finish_selection()
    proc.provide_text("Crate")
    assert len(scene.block_defs) == 1
    instances = [o for o in scene.all() if o.block_id]
    assert len(instances) == 1

    proc.run("insert")
    proc.provide_text("Crate")
    proc.provide_text("10,0,0")
    instances = [o for o in scene.all() if o.block_id]
    assert len(instances) == 2
    mn, _ = g.bbox(instances[-1].shape)
    assert mn[0] == pytest.approx(10, abs=1e-6)


def test_block_persistence(env, tmp_path):
    from serpentine3d import fileio
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_box((0, 0, 0), 2, 2, 2))
    proc.run("block")
    proc.click_object(a.id)
    proc.finish_selection()
    proc.provide_text("Unit")
    proc.run("lock")
    proc.click_object(scene.all()[0].id)
    proc.finish_selection()

    path = str(tmp_path / "blocks.serp")
    fileio.export_file(scene, path)
    from serpentine3d.core.scene import Scene
    loaded = Scene()
    fileio.import_file(loaded, path)
    assert len(loaded.block_defs) == 1
    assert loaded.all()[0].block_id
    assert loaded.all()[0].locked


def test_subobject_filletedge_and_pushpull(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))

    # fillet only edge 0
    sel.toggle_subobject(box.id, "edge", 0)
    proc.run("filletedge")
    proc.provide_text("No")          # no chain expansion
    proc.provide_text("1")
    v = g.volume(scene.all()[0].shape)
    # one rounded edge: 10x10x10 minus one quarter-round strip
    expected = 1000 - (1 - 3.14159 / 4) * 1 * 10
    assert v == pytest.approx(expected, rel=1e-3)
    assert sel.subobjects == []

    # push a face outward by 5: find the +X face index
    shape = scene.all()[0].shape
    import numpy as np
    faces = g.faces_of(shape)
    xmax_idx = max(range(len(faces)),
                   key=lambda i: g.centroid(faces[i])[0])
    v0 = g.volume(shape)
    sel.toggle_subobject(box.id, "face", xmax_idx)
    proc.run("pushpull")
    proc.provide_text("5")
    v1 = g.volume(scene.all()[0].shape)
    assert v1 > v0 + 400          # roughly +500 minus the filleted strip

    # carve inward
    shape = scene.all()[0].shape
    faces = g.faces_of(shape)
    xmax_idx = max(range(len(faces)),
                   key=lambda i: g.centroid(faces[i])[0])
    sel.toggle_subobject(box.id, "face", xmax_idx)
    proc.run("pushpull")
    proc.provide_text("-3")
    v2 = g.volume(scene.all()[0].shape)
    assert v2 < v1


def test_command_option_chips(env):
    """Options are settable any time during a request, Rhino-style."""
    scene, sel, hist, ctx, proc = env
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("extrude")
    proc.click_object(c.id)
    proc.finish_selection()
    chips = dict(proc.option_chips())
    assert chips == {"Cap": "Yes", "BothSides": "No"}
    proc.provide_text("BothSides=Yes")        # option text does not advance
    proc.provide_text("cap=n")                # prefix match, case-insensitive
    assert dict(proc.option_chips()) == {"Cap": "No", "BothSides": "Yes"}
    assert proc.set_option("Cap")             # click = cycle
    assert dict(proc.option_chips())["Cap"] == "Yes"
    proc.provide_text("10")
    assert not proc.busy
    solid = scene.all()[-1]
    (zmin, zmax) = (g.bbox(solid.shape)[0][2], g.bbox(solid.shape)[1][2])
    assert zmin == pytest.approx(-10) and zmax == pytest.approx(10)
    import math
    assert g.volume(solid.shape) == pytest.approx(math.pi * 25 * 20,
                                                  rel=1e-3)


def test_command_live_preview(env):
    scene, sel, hist, ctx, proc = env
    c = scene.add(g.make_circle((0, 0, 0), 5))
    proc.run("extrude")
    proc.click_object(c.id)
    proc.finish_selection()
    ghost = proc.preview_shape("7")
    assert ghost is not None
    assert g.bbox(ghost)[1][2] == pytest.approx(7)
    assert proc.preview_shape("not a number") is None
    assert proc.busy                          # preview never advances
    proc.cancel()


def test_loft_style_option(env):
    scene, sel, hist, ctx, proc = env
    c1 = scene.add(g.make_circle((0, 0, 0), 5))
    c2 = scene.add(g.make_circle((0, 0, 10), 3))
    proc.run("loft")
    proc.click_object(c1.id)
    proc.click_object(c2.id)
    proc.provide_text("Style=Ruled")
    proc.finish_selection()
    assert not proc.busy
    assert scene.all()[-1].kind in ("surface", "solid")


def test_help_command(env):
    scene, sel, hist, ctx, proc = env
    echoes = []
    ctx.add_echo_listener(echoes.append)
    proc.run("help")
    proc.provide_text("extrude")
    assert any("extrude" in e and "ext" in e for e in echoes)
    proc.run("help")
    proc.provide_text("")
    assert any(e.startswith("Surfaces:") for e in echoes)


def test_zoom_commands(env):
    scene, sel, hist, ctx, proc = env
    from tests.conftest import StubViewport

    class ZoomStub(StubViewport):
        def __init__(self):
            super().__init__("model")
            self.calls = []

        def zoom_selected(self):
            self.calls.append("selected")
            return bool(sel.ids)

        def zoom_extents(self):
            self.calls.append("extents")

        def zoom_to_points(self, p1, p2):
            self.calls.append(("window", p1, p2))

    vp = ZoomStub()
    ctx.viewport = vp
    obj = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    sel.set([obj.id])
    proc.run("zoomselected")
    assert vp.calls[-1] == "selected"
    proc.run("zoom")
    proc.provide_text("")          # default Selected (something is selected)
    assert vp.calls[-1] == "selected"
    proc.run("zoomwindow")
    proc.provide_text("0,0,0")
    proc.provide_text("10,10,0")
    assert vp.calls[-1] == ("window", (0, 0, 0), (10, 10, 0))
    sel.clear()
    proc.run("zoom")
    proc.provide_text("Extents")
    assert vp.calls[-1] == "extents"


def test_zoom_selected_math():
    import numpy as np
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    far = scene.add(g.make_box((100, 100, 100), 2, 2, 2))
    sel.set([far.id])
    assert vp.zoom_selected()
    assert np.allclose(vp.camera.target, (101, 101, 101))
    assert vp.camera.distance < 30            # framed tight, not extents
    vp.zoom_to_points((0, 0, 0), (10, 10, 0))
    assert np.allclose(vp.camera.target, (5, 5, 0), atol=0.01)


def test_box_click_height_flow(env):
    """box: rect preview after 2 corners, click/typed height, axis lock."""
    scene, sel, hist, ctx, proc = env
    proc.run("box")
    proc.provide_text("0,0,0")
    # rectangle preview follows the candidate second corner
    ghost = proc.preview_for((10, 6, 0))
    assert ghost is not None and g.shape_kind(ghost) == "curve"
    proc.provide_text("10,6,0")
    req = proc.request
    assert req.axis_lock == ((10, 6, 0), (0.0, 0.0, 1.0))
    # box preview materialises toward the candidate height point
    ghost = proc.preview_for((10, 6, 8))
    assert g.shape_kind(ghost) == "solid"
    assert g.volume(ghost) == pytest.approx(10 * 6 * 8)
    proc.preview_for((10, 6, 0)) is None            # degenerate -> no ghost
    # typed bare number resolves along the axis (E2E compatibility)
    proc.provide_text("8")
    assert not proc.busy
    assert g.volume(scene.all()[0].shape) == pytest.approx(480)


def test_box_negative_height_and_zero(env):
    scene, sel, hist, ctx, proc = env
    proc.run("box")
    proc.provide_text("0,0,0")
    proc.provide_text("4,4,0")
    proc.provide_text("-5")                  # downward box
    box = scene.all()[0]
    assert g.volume(box.shape) == pytest.approx(80)
    assert g.bbox(box.shape)[0][2] == pytest.approx(-5)
    proc.run("box")
    proc.provide_text("0,0,20")
    proc.provide_text("4,4,20")
    proc.provide_text("0")                   # zero height refused
    assert not proc.busy and len(scene.all()) == 1


def test_cylinder_and_circle_click_radius(env):
    scene, sel, hist, ctx, proc = env
    import math
    proc.run("cylinder")
    proc.provide_text("0,0,0")
    ghost = proc.preview_for((3, 4, 0))      # radius 5 by click
    assert g.shape_kind(ghost) == "curve"
    proc.provide_text("3,4,0")
    proc.provide_text("7")
    cyl = scene.all()[-1]
    assert g.volume(cyl.shape) == pytest.approx(math.pi * 25 * 7, rel=1e-3)

    proc.run("circle")
    proc.provide_text("0,0,0")
    proc.provide_text("5")                   # typed radius still works
    circ = scene.all()[-1]
    assert circ.kind == "curve"
    assert g.curve_length(circ.shape) == pytest.approx(2 * math.pi * 5,
                                                       rel=1e-3)


def test_point_axis_lock_in_viewport():
    import numpy as np
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.point_mode = True
    vp.point_axis = ((5, 5, 0), (0, 0, 1))
    # any pixel resolves to a point on the vertical axis through (5,5,0)
    pt = vp.world_point_at(400, 200)
    assert pt is not None
    assert pt[0] == pytest.approx(5) and pt[1] == pytest.approx(5)
    pt_lower = vp.world_point_at(400, 500)
    assert pt_lower[2] < pt[2]              # lower pixel -> lower height
