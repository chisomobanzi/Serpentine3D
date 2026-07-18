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


def test_dot_command_and_roundtrip(env, tmp_path):
    scene, sel, hist, ctx, proc = env
    proc.run("dot")
    proc.provide_text("5,5,0")
    proc.provide_text("STAGE LEFT")
    proc.provide_text("")
    assert not proc.busy
    dots = [o for o in scene.all() if o.annotation]
    assert len(dots) == 1
    assert dots[0].kind == "point"
    assert dots[0].annotation["text"] == "STAGE LEFT"

    from serpentine3d.fileio.native import load_scene, save_scene
    path = str(tmp_path / "dots.serp")
    save_scene(scene, path)
    from serpentine3d.core.scene import Scene
    scene2 = Scene()
    load_scene(scene2, path)
    dots2 = [o for o in scene2.all() if o.annotation]
    assert len(dots2) == 1
    assert dots2[0].annotation["text"] == "STAGE LEFT"


def test_copy_preserves_attributes(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_point((0, 0, 0)))
    scene.update(obj.id, annotation={"text": "PROP"},
                 color=(1.0, 0.0, 0.0), material={"opacity": 0.5})
    proc.run("copy")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("")
    copies = [o for o in scene.all() if o.id != obj.id]
    assert len(copies) == 1
    c = copies[0]
    assert c.annotation == {"text": "PROP"}
    assert c.color == (1.0, 0.0, 0.0)
    assert c.material == {"opacity": 0.5}
    assert g.point_coords(c.shape) == pytest.approx((10, 0, 0))


def test_mirror_copy_preserves_attributes(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_line((1, 0, 0), (2, 0, 0)))
    scene.update(obj.id, color=(0.0, 1.0, 0.0))
    proc.run("mirror")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("0,1,0")
    proc.provide_text("Yes")   # keep original
    copies = [o for o in scene.all() if o.id != obj.id]
    assert len(copies) == 1
    assert copies[0].color == (0.0, 1.0, 0.0)


def test_rotate3d_command(env):
    scene, sel, hist, ctx, proc = env
    # line along X at z=0; rotate 90° around the X axis itself
    obj = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    tip = scene.add(g.make_point((5, 3, 0)))
    proc.run("rotate3d")
    proc.click_object(tip.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("90")
    assert not proc.busy
    assert g.point_coords(scene.get(tip.id).shape) == pytest.approx(
        (5, 0, 3), abs=1e-6)


def test_rotate3d_copy_option(env):
    scene, sel, hist, ctx, proc = env
    tip = scene.add(g.make_point((5, 3, 0)))
    proc.run("rotate3d")
    proc.click_object(tip.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("Copy=Yes")
    proc.provide_text("90")
    assert len(scene.all()) == 2


def test_tweencurves_command(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    b = scene.add(g.make_line((0, 10, 0), (10, 10, 0)))
    proc.run("tweencurves")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.provide_text("2")
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 4  # 2 originals + 2 tweens


def test_smooth_command(env):
    scene, sel, hist, ctx, proc = env
    pts = [(x, (2 if x % 2 else -2), 0) for x in range(9)]
    zig = scene.add(g.make_interp_curve(pts))
    before = g.curve_length(zig.shape)
    proc.run("smooth")
    proc.click_object(zig.id)
    proc.finish_selection()
    proc.provide_text("0.4")
    assert g.curve_length(scene.get(zig.id).shape) < before


def test_setpt_command_flatten(env):
    scene, sel, hist, ctx, proc = env
    wavy = scene.add(g.make_interp_curve([(0, 0, 0), (5, 2, 3),
                                          (10, -1, 6)]))
    proc.run("setpt")
    proc.click_object(wavy.id)
    proc.finish_selection()
    proc.provide_text("0,0,1")
    assert not proc.busy
    (mn, mx) = g.bbox(scene.get(wavy.id).shape)
    assert mn[2] == pytest.approx(1, abs=1e-6)
    assert mx[2] == pytest.approx(1, abs=1e-6)


def test_setpt_command_align_x(env):
    scene, sel, hist, ctx, proc = env
    p = scene.add(g.make_point((3, 4, 5)))
    proc.run("setpt")
    proc.click_object(p.id)
    proc.finish_selection()
    proc.provide_text("X=Yes")
    proc.provide_text("Z=No")
    proc.provide_text("7,0,0")
    assert g.point_coords(scene.get(p.id).shape) == pytest.approx((7, 4, 5))


def test_dupfaceborder_command(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 2, 3, 4))
    sel.subobjects.append((box.id, "face", 0))
    proc.run("dupfaceborder")
    assert not proc.busy
    curves = [o for o in scene.all() if o.kind == "curve"]
    assert len(curves) == 1
    # one rectangular border of some box face
    assert g.is_closed_curve(curves[0].shape)
    assert g.curve_length(curves[0].shape) in (
        pytest.approx(10.0), pytest.approx(12.0), pytest.approx(14.0))


def test_smooth_command_on_polyline(env):
    scene, sel, hist, ctx, proc = env
    pts = [(x, (2 if x % 2 else -2), 0) for x in range(9)]
    zig = scene.add(g.make_polyline(pts))
    before = g.curve_length(zig.shape)
    proc.run("smooth")
    proc.click_object(zig.id)
    proc.finish_selection()
    proc.provide_text("0.5")
    after = scene.get(zig.id)
    assert g.curve_length(after.shape) < before


def test_chamfer_command(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    b = scene.add(g.make_line((10, 0, 0), (10, 10, 0)))
    proc.run("chamfer")
    proc.click_object(a.id)
    proc.click_object(b.id)
    proc.provide_text("2")
    assert not proc.busy
    assert len(scene.all()) == 1
    joined = scene.all()[0]
    assert g.curve_length(joined.shape) == pytest.approx(16 + 8 ** 0.5)


def test_selprev_command(env):
    scene, sel, hist, ctx, proc = env
    a = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    b = scene.add(g.make_line((0, 1, 0), (1, 1, 0)))
    sel.set([a.id, b.id])
    sel.clear()
    assert sel.ids == []
    proc.run("selprev")
    assert sorted(sel.ids) == sorted([a.id, b.id])


def test_matchprops_command(env):
    scene, sel, hist, ctx, proc = env
    used = scene.layers.create("Walls")
    src = scene.add(g.make_line((0, 0, 0), (1, 0, 0)), layer_id=used.id)
    scene.update(src.id, color=(1, 0, 0), material={"opacity": 0.4})
    dst = scene.add(g.make_line((0, 5, 0), (1, 5, 0)))
    proc.run("matchprops")
    proc.click_object(src.id)
    proc.click_object(dst.id)
    proc.finish_selection()
    d = scene.get(dst.id)
    assert d.layer_id == used.id
    assert d.color == (1, 0, 0)
    assert d.material == {"opacity": 0.4}


def test_changelayer_command(env):
    scene, sel, hist, ctx, proc = env
    obj = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    proc.run("changelayer")
    proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("Set Walls")
    layer = scene.layers.find_by_name("Set Walls")
    assert layer is not None
    assert scene.get(obj.id).layer_id == layer.id


def test_audit_command(env):
    scene, sel, hist, ctx, proc = env
    msgs = []
    ctx.add_echo_listener(msgs.append)
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    proc.run("audit")
    assert "valid" in "\n".join(msgs)


def test_projecttocplane_command(env):
    scene, sel, hist, ctx, proc = env
    wavy = scene.add(g.make_interp_curve([(0, 0, 1), (5, 2, 4),
                                          (10, -1, 2)]))
    proc.run("projecttocplane")
    proc.click_object(wavy.id)
    proc.finish_selection()
    (mn, mx) = g.bbox(scene.get(wavy.id).shape)
    assert mn[2] == pytest.approx(0, abs=1e-6)
    assert mx[2] == pytest.approx(0, abs=1e-6)


def test_angle_command(env):
    scene, sel, hist, ctx, proc = env
    msgs = []
    ctx.add_echo_listener(msgs.append)
    proc.run("angle")
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("0,10,0")
    assert any("90" in m for m in msgs)


def test_geometry_chamfer_and_project():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((10, 0, 0), (10, 10, 0))
    ea, bevel, eb = g.chamfer_curves(a, b, 2.0)
    total = g.curve_length(g.join_curves([ea, bevel, eb]))
    assert total == pytest.approx(16 + 8 ** 0.5)

    tilted = g.make_line((0, 0, 5), (10, 0, 8))
    flat = g.project_to_plane(tilted, (0, 0, 2), (0, 0, 1))
    (mn, mx) = g.bbox(flat)
    assert mn[2] == pytest.approx(2, abs=1e-6)
    assert mx[2] == pytest.approx(2, abs=1e-6)


def test_radius_command(env):
    scene, sel, hist, ctx, proc = env
    msgs = []
    ctx.add_echo_listener(msgs.append)
    circle = scene.add(g.make_circle((0, 0, 0), 7))
    proc.run("radius")
    proc.click_object(circle.id)
    proc.provide_text("7,0,0")
    assert not proc.busy
    assert any("Radius: 7" in m for m in msgs)


def test_scale1d_command(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run("scale1d")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("10,0,0")
    proc.provide_text("2")
    (mn, mx) = g.bbox(scene.get(box.id).shape)
    assert mx[0] == pytest.approx(20, abs=1e-6)
    assert mx[1] == pytest.approx(10, abs=1e-6)
    assert mx[2] == pytest.approx(10, abs=1e-6)


def test_scale2d_command(env):
    scene, sel, hist, ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    proc.run("scale2d")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("0,0,0")
    proc.provide_text("3")
    (mn, mx) = g.bbox(scene.get(box.id).shape)
    assert mx[0] == pytest.approx(30, abs=1e-5)
    assert mx[1] == pytest.approx(30, abs=1e-5)
    assert mx[2] == pytest.approx(10, abs=1e-5)


def test_fuzzy_score_ranking():
    from serpentine3d.ui.palette import fuzzy_score
    assert fuzzy_score("", "line") == 0
    assert fuzzy_score("xyz", "line") is None
    exact = fuzzy_score("line", "line")
    sub = fuzzy_score("lin", "polyline")
    assert exact is not None and sub is not None
    assert exact > sub
    # word-start bonus: 'ze' should hit zoomextents strongly
    assert fuzzy_score("ze", "zoomextents") > fuzzy_score("ze", "size")
