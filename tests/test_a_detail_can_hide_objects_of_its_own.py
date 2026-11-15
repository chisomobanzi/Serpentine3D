"""A detail can hide objects of its own and leave the model, and every other
detail, as they were.

As in Rhino, inside a detail `hideindetail` hides the objects you pick in
that detail only, `showindetail` brings back all it hid, and
`showselectedindetail` brings back the ones you pick, with them on show
while it asks, the way `showselected` does in the model. A detail could
already leave out whole layers (#38); this is the same for single objects.

A detail keeps them by id beside its hidden layers, so a .serp keeps them.
0.12.4 opens a newer drawing's details and lets a field it does not know
go without a word, so a drawing using this asks for the release that keeps
it.
"""

from __future__ import annotations

import json
import zipfile

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.core.scene import Scene
from serpentine3d.ui.camera import STANDARD_VIEWS

NEXT = "0.13.0"


def _box(scene, name, x=0.0):
    return scene.add(g.make_box((x, 0, 0), 10, 10, 10), name=name)


def _sheet(scene):
    az, el = STANDARD_VIEWS["front"]
    plan = DetailView(x=20, y=40, w=180, h=150, azimuth=az, elevation=el,
                      target=[30.0, 0.0, 0.0], scale_denom=1.0,
                      display_mode="hidden")
    other = DetailView(x=210, y=40, w=180, h=150, azimuth=az, elevation=el,
                       target=[30.0, 0.0, 0.0], scale_denom=1.0,
                       display_mode="hidden")
    lay = Layout(name="Sheet")
    lay.details.extend([plan, other])
    scene.layouts.append(lay)
    return lay, plan, other


def _inside(ctx, detail):
    """Put the command inside `detail`, as a double-click does."""
    from tests.conftest import StubViewport

    class Pane(StubViewport):
        def update(self):
            pass

    pane = Pane("sheet")
    pane.layout_view.entered_detail = detail.id
    pane.layout_view._entered = lambda: detail
    ctx.viewport = pane


def test_a_pick_that_fails_to_start_leaves_nothing_on_show(env):
    """Whatever goes wrong putting them on show, they come off again."""
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id]
    _inside(ctx, plan)

    def broken():
        raise RuntimeError("no paint today")

    ctx.viewport.update = broken
    proc.run("showselectedindetail")
    assert scene.showing_only is None


def _drawing(env):
    scene, sel, hist, ctx, proc = env
    a, b, c = (_box(scene, n, x) for n, x in (("A", 0.0), ("B", 30.0),
                                             ("C", 60.0)))
    lay, plan, other = _sheet(scene)
    return a, b, c, lay, plan, other


# -- hideindetail ------------------------------------------------------------------

def test_hiding_in_a_detail_leaves_the_model_and_the_other_detail(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    _inside(ctx, plan)
    sel.set([a.id, b.id])
    proc.run("hideindetail")
    assert not proc.busy
    assert sorted(plan.hidden_objects) == sorted([a.id, b.id])
    assert other.hidden_objects == []
    assert scene.get(a.id).visible and scene.get(b.id).visible


def test_hiding_again_does_not_list_an_object_twice(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    _inside(ctx, plan)
    sel.set([a.id])
    proc.run("hideindetail")
    sel.set([a.id, c.id])
    proc.run("hideindetail")
    assert sorted(plan.hidden_objects) == sorted([a.id, c.id])


def test_outside_a_detail_it_says_where_to_go(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    said = []
    ctx.add_echo_listener(said.append)
    from tests.conftest import StubViewport
    ctx.viewport = StubViewport("model")
    sel.set([a.id])
    proc.run("hideindetail")
    assert not proc.busy
    assert plan.hidden_objects == [] and other.hidden_objects == []
    assert any("detail" in line for line in said)


def test_one_undo_brings_them_back(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    _inside(ctx, plan)
    sel.set([a.id])
    proc.run("hideindetail")
    hist.undo()
    (back,) = [d for d in scene.layouts[0].details if d.id == plan.id]
    assert back.hidden_objects == []
    hist.redo()
    (redone,) = [d for d in scene.layouts[0].details if d.id == plan.id]
    assert redone.hidden_objects == [a.id]
    assert scene.get(a.id).visible


def test_cancelling_a_hide_changes_nothing(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    _inside(ctx, plan)
    proc.run("hideindetail")
    assert proc.busy
    proc.click_object(a.id)
    proc.cancel()
    assert not proc.busy
    assert plan.hidden_objects == []
    assert scene.get(a.id).visible


# -- showindetail ------------------------------------------------------------------

def test_show_in_detail_brings_back_all_it_hid(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id, b.id]
    other.hidden_objects = [a.id]
    _inside(ctx, plan)
    proc.run("showindetail")
    assert plan.hidden_objects == []
    assert other.hidden_objects == [a.id]


# -- showselectedindetail -----------------------------------------------------------

def test_while_it_waits_what_this_detail_hid_is_on_show(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id, b.id]
    _inside(ctx, plan)
    proc.run("showselectedindetail")
    assert proc.busy
    assert scene.showing_only == frozenset({a.id, b.id})


def test_the_picked_come_back_in_the_detail_and_the_rest_stay_hidden(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id, b.id]
    _inside(ctx, plan)
    proc.run("showselectedindetail")
    proc.click_object(b.id)
    proc.finish_selection()
    assert not proc.busy
    assert scene.showing_only is None
    assert plan.hidden_objects == [a.id]


def test_escape_in_the_detail_changes_nothing(env):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id, b.id]
    _inside(ctx, plan)
    proc.run("showselectedindetail")
    proc.cancel()
    assert scene.showing_only is None
    assert plan.hidden_objects == [a.id, b.id]


@pytest.mark.parametrize("command", ["showindetail", "showselectedindetail"])
def test_restoring_in_a_detail_can_be_undone_and_redone(env, command):
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    plan.hidden_objects = [a.id, b.id]
    other.hidden_objects = [a.id]
    _inside(ctx, plan)
    proc.run(command)
    if command == "showselectedindetail":
        assert proc.busy
        proc.click_object(b.id)
        proc.finish_selection()
    expected = [] if command == "showindetail" else [a.id]
    assert plan.hidden_objects == expected
    hist.undo()
    back, other_back = scene.layouts[0].details
    assert back.hidden_objects == [a.id, b.id]
    assert other_back.hidden_objects == [a.id]
    hist.redo()
    redone, other_redone = scene.layouts[0].details
    assert redone.hidden_objects == expected
    assert other_redone.hidden_objects == [a.id]
    assert scene.showing_only is None


def test_what_would_not_appear_anyway_is_not_offered(env):
    """Hidden in the model, or on a layer this detail leaves out: shown
    here, it would still not be seen."""
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    walls = scene.layers.create("Walls")
    interior = scene.layers.create("Interior", parent=walls.id)
    scene.update(b.id, layer_id=walls.id)
    scene.update(c.id, visible=False)
    d = _box(scene, "D", 90.0)
    scene.update(d.id, layer_id=interior.id)
    global_hidden = scene.layers.create("Hidden everywhere")
    e = _box(scene, "E", 120.0)
    scene.update(e.id, layer_id=global_hidden.id)
    scene.layers.set_visible(global_hidden.id, False)
    plan.hidden_layers = [walls.id]
    plan.hidden_objects = [a.id, b.id, c.id, d.id, e.id]
    _inside(ctx, plan)
    proc.run("showselectedindetail")
    assert scene.showing_only == frozenset({a.id})
    proc.cancel()


def test_with_nothing_hidden_in_the_detail_it_says_so(env):
    scene, sel, hist, ctx, proc = env
    _drawing(env)
    plan = scene.layouts[0].details[0]
    said = []
    ctx.add_echo_listener(said.append)
    _inside(ctx, plan)
    proc.run("showselectedindetail")
    assert not proc.busy
    assert scene.showing_only is None
    assert any("nothing hidden" in line.lower() for line in said)


# -- drawing and picking -------------------------------------------------------------

@pytest.fixture
def window(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.viewport.resize(900, 700)
    a, b = _box(w.scene, "A"), _box(w.scene, "B", 30.0)
    lay, plan, other = _sheet(w.scene)
    w.switch_space(lay.id)
    yield w, a, b, plan, other
    w.mark_saved()
    w.close()


def _drawn_in(lv, det) -> set:
    return {oid for oid, _lt, polys in lv._detail_hlr(det)["visible_by_obj"]
            if polys}


def test_a_hidden_line_detail_leaves_out_what_it_hid(window):
    w, a, b, plan, other = window
    lv = w.viewport.layout_view
    assert _drawn_in(lv, plan) == {a.id, b.id}
    plan.hidden_objects = [a.id]
    w.scene.notify("layouts")
    assert _drawn_in(lv, plan) == {b.id}
    assert _drawn_in(lv, other) == {a.id, b.id}


def test_a_shaded_detail_leaves_out_what_it_hid(window):
    from PySide6.QtWidgets import QApplication
    from tests.test_a_detail_hides_layers_of_its_own import _has

    w, a, b, plan, other = window
    vp = w.viewport
    if QApplication.instance().platformName() == "offscreen":
        pytest.skip("no real GL surface offscreen (CI runs offscreen)")
    w.show()
    vp.grabFramebuffer()
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        pytest.skip("no GL 3.3 to draw with here")
    red = w.scene.layers.create("Red", color=(1.0, 0.0, 0.0))
    blue = w.scene.layers.create("Blue", color=(0.0, 0.0, 1.0))
    w.scene.update(a.id, layer_id=red.id)
    w.scene.update(b.id, layer_id=blue.id)
    plan.display_mode = "shaded"
    whole = vp.render_detail_image(plan, 480, 300)
    assert whole is not None and _has(whole, (230, 40, 40))
    plan.hidden_objects = [a.id]
    w.scene.notify("layouts")
    image = vp.render_detail_image(plan, 480, 300)
    assert image is not None and not _has(image, (230, 40, 40))
    assert _has(image, (40, 40, 230))


def test_a_shaded_detail_leaves_out_one_of_a_row_of_alike_objects(window):
    """Alike objects go up as one mesh (#154). The one a detail hid must
    not come back with the rest of its row."""
    from PySide6.QtWidgets import QApplication

    w, a, b, plan, other = window
    vp = w.viewport
    if QApplication.instance().platformName() == "offscreen":
        pytest.skip("no real GL surface offscreen (CI runs offscreen)")
    w.show()
    vp.grabFramebuffer()
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        pytest.skip("no GL 3.3 to draw with here")
    red = w.scene.layers.create("Red", color=(1.0, 0.0, 0.0))
    row = [a, _box(w.scene, "C", 15.0), b, _box(w.scene, "D", 45.0),
           _box(w.scene, "E", 60.0)]
    for obj in row:
        w.scene.update(obj.id, layer_id=red.id)
        assert obj.mesh is not None
    plan.display_mode = "shaded"
    whole = _count(vp.render_detail_image(plan, 480, 300), (230, 40, 40))
    plan.hidden_objects = [b.id]
    w.scene.notify("layouts")
    left = _count(vp.render_detail_image(plan, 480, 300), (230, 40, 40))
    assert any(batch.last_draw == vp._batch_draws
               for batch in vp._batches.values())
    assert 0.7 < left / whole < 0.9


def _count(image, rgb) -> int:
    """Pixels close to `rgb`."""
    assert image is not None
    return sum(
        all(abs(c - want) < 40 for c, want in
            zip(image.pixelColor(x, y).getRgb()[:3], rgb))
        for x in range(image.width()) for y in range(image.height()))


def test_inside_a_detail_what_it_hid_cannot_be_picked(window):
    """Nor can what is on a layer it leaves out: neither is there to see."""
    w, a, b, plan, other = window
    vp = w.viewport
    from tests.test_what_a_clipping_plane_cuts_away_cannot_be_picked import (
        _band, _click)

    vp.layout_view.fit()
    vp.layout_view.entered_detail = plan.id
    assert a.id in _click(vp, (0, 0, 5))
    assert b.id in _click(vp, (30, 0, 5))
    walls = w.scene.layers.create("Walls")
    inner = w.scene.layers.create("Interior", parent=walls.id)
    w.scene.update(b.id, layer_id=inner.id)
    plan.hidden_objects = [a.id]
    plan.hidden_layers = [walls.id]
    w.scene.notify("layouts")
    assert a.id not in _click(vp, (0, 0, 5))
    assert a.id not in _band(vp, (0, 0, 5))
    assert b.id not in _click(vp, (30, 0, 5))
    assert b.id not in _band(vp, (30, 0, 5))
    vp.layout_view.entered_detail = other.id
    assert a.id in _click(vp, (0, 0, 5))
    assert b.id in _click(vp, (30, 0, 5))


def test_while_a_pick_puts_them_on_show_the_detail_draws_them(window):
    from tests.test_what_a_clipping_plane_cuts_away_cannot_be_picked import _click

    w, a, b, plan, other = window
    vp = w.viewport
    vp.layout_view.fit()
    plan.hidden_objects = [a.id]
    vp.layout_view.entered_detail = plan.id
    w.scene.showing_only = frozenset({a.id})
    try:
        assert _drawn_in(vp.layout_view, plan) == {a.id}
        assert a.id in _click(vp, (0, 0, 5))
        assert b.id not in _click(vp, (30, 0, 5))
    finally:
        w.scene.showing_only = None


def test_hiding_an_object_in_a_detail_keeps_its_clipping_rules(_qapp):
    """Click and band selection respect both the detail's hidden objects
    and its existing clipping switches, including after restoring one."""
    from serpentine3d.core import clipping
    from serpentine3d.core.pointcloud import PointCloudShape
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    from tests.test_what_a_clipping_plane_cuts_away_cannot_be_picked import (
        ABOVE, BELOW, _band, _click, _plane)

    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    vp.set_view("front")
    cloud = scene.add(PointCloudShape([ABOVE, BELOW]), name="Scan")
    lay, plan, other = _sheet(scene)
    plan.target = other.target = [0.0, 0.0, 0.0]
    vp.set_space(lay.id)
    vp.layout_view.fit()
    vp.layout_view.entered_detail = plan.id
    plane = _plane(scene, off_in=[vp.view_key])
    assert cloud.id not in _click(vp, ABOVE)
    assert cloud.id not in _band(vp, ABOVE)
    assert cloud.id in _click(vp, BELOW)
    assert cloud.id in _band(vp, BELOW)

    plan.hidden_objects = [cloud.id]
    scene.notify("layouts")
    assert cloud.id not in _click(vp, BELOW)
    assert cloud.id not in _band(vp, BELOW)
    clipping.switch(scene, plane.id, plan.id, False)
    assert cloud.id not in _click(vp, ABOVE)
    assert cloud.id not in _band(vp, ABOVE)

    plan.hidden_objects = []
    scene.notify("layouts")
    assert cloud.id in _click(vp, ABOVE)
    assert cloud.id in _band(vp, ABOVE)
    vp.layout_view.entered_detail = other.id
    assert cloud.id not in _click(vp, ABOVE)
    assert cloud.id not in _band(vp, ABOVE)
    assert cloud.id in _click(vp, BELOW)


def test_the_pdf_leaves_out_the_same_hidden_object(window):
    from serpentine3d.fileio import pdf

    w, a, b, plan, other = window
    lay = w.scene.layouts[0]

    class Recorder:
        def __init__(self):
            self.points = []

        def save(self): pass
        def restore(self): pass
        def setClipRect(self, *args): pass
        def setPen(self, pen): pass

        def drawPolyline(self, poly):
            self.points.extend((p.x(), p.y()) for p in poly)

        def drawLine(self, a, b):
            self.points.extend(((a.x(), a.y()), (b.x(), b.y())))

    def bounds(det):
        rec = Recorder()
        pdf._paint_detail_vector(rec, w.viewport.layout_view, det, lay, 1.0)
        assert rec.points, "the PDF drew nothing, so the test proves nothing"
        xs = [x for x, _y in rec.points]
        return min(xs), max(xs)

    whole, other_whole = bounds(plan), bounds(other)
    plan.hidden_objects = [a.id]
    w.scene.notify("layouts")
    assert bounds(plan) == pytest.approx((whole[0] + 30.0, whole[1]))
    assert bounds(other) == pytest.approx(other_whole)


def test_the_dxf_leaves_out_the_same_hidden_object(window, tmp_path):
    import ezdxf
    from serpentine3d.fileio.dxf import export_layout_dxf

    w, a, b, plan, other = window
    lay = w.scene.layouts[0]

    def bounds(name):
        path = str(tmp_path / name)
        export_layout_dxf(w, lay, path)
        doc = ezdxf.readfile(path)
        xs = [float(p[0]) for entity in doc.modelspace()
              if entity.dxftype() == "LWPOLYLINE"
              and entity.dxf.layer == "VISIBLE"
              for p in entity.get_points()]
        assert xs, "the DXF drew nothing, so the test proves nothing"
        plan_xs = [x for x in xs if x < 200.0]
        other_xs = [x for x in xs if x > 210.0]
        return ((min(plan_xs), max(plan_xs)),
                (min(other_xs), max(other_xs)))

    whole, other_whole = bounds("whole.dxf")
    plan.hidden_objects = [a.id]
    w.scene.notify("layouts")
    hidden, other_after = bounds("hidden.dxf")
    assert hidden == pytest.approx((whole[0] + 30.0, whole[1]))
    assert other_after == pytest.approx(other_whole)


# -- the file --------------------------------------------------------------------------

def _saved(scene, tmp_path):
    from serpentine3d.fileio import native
    path = str(tmp_path / "drawing.serp")
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json")), path


def test_a_detail_keeps_what_it_hid_through_a_file(tmp_path):
    from serpentine3d.fileio import native
    scene = Scene()
    a = _box(scene, "A")
    lay, plan, other = _sheet(scene)
    plan.hidden_objects = [a.id]
    _doc, path = _saved(scene, tmp_path)
    back = Scene()
    native.load_scene(back, path)
    (plan_back, other_back) = back.layouts[0].details
    (hidden,) = plan_back.hidden_objects
    assert back.get(hidden).name == "A", \
        "the object it hid, under the id it has now"
    assert other_back.hidden_objects == []


def test_a_drawing_using_it_asks_for_the_release_that_keeps_it(tmp_path,
                                                                monkeypatch):
    from serpentine3d.fileio import native
    scene = Scene()
    a = _box(scene, "A")
    lay, plan, other = _sheet(scene)
    plan.hidden_objects = [a.id]
    doc, path = _saved(scene, tmp_path)
    assert doc["requires"] == NEXT
    assert doc["version"] == 9         # published 0.12.4 reads up to version 8
    monkeypatch.setattr(native, "FORMAT_VERSION", 8)
    with pytest.raises(ValueError, match=NEXT):
        native.load_scene(Scene(), path)


def test_a_dimension_and_what_a_detail_hid_share_one_file(tmp_path,
                                                          monkeypatch):
    """0.13.0's two kinds of new data, a model dimension (#124) and a
    detail's own hidden objects, go into one version-9 file and come back
    together; an older reader refuses it, naming 0.13.0."""
    from serpentine3d.core.dimension import DimensionShape
    from serpentine3d.fileio import native
    scene = Scene()
    a = _box(scene, "A")
    dim = scene.add(DimensionShape((0, 0, 0), (10, 0, 0), (0, -5, 0)))
    lay, plan, other = _sheet(scene)
    plan.hidden_objects = [dim.id]
    doc, path = _saved(scene, tmp_path)
    assert (doc["version"], doc["requires"]) == (9, NEXT)
    back = Scene()
    native.load_scene(back, path)
    (hidden,) = back.layouts[0].details[0].hidden_objects
    assert isinstance(back.get(hidden).shape, DimensionShape)
    assert back.get(hidden).shape.label == "10.00"
    assert [o.name for o in back.all()
            if not isinstance(o.shape, DimensionShape)] == ["A"]
    monkeypatch.setattr(native, "FORMAT_VERSION", 8)
    with pytest.raises(ValueError, match=NEXT):
        native.load_scene(Scene(), path)


def test_a_drawing_not_using_it_is_written_as_before(tmp_path):
    scene = Scene()
    _box(scene, "A")
    _sheet(scene)
    doc, _path = _saved(scene, tmp_path)
    assert doc.get("requires") != NEXT
    assert doc["version"] <= 8



# -- with alike objects sharing a draw call (#154) -----------------------------

@pytest.fixture
def gl(monkeypatch):
    from serpentine3d.ui import gpu_share
    from serpentine3d.ui import viewport as vp_mod
    from tests.test_alike_objects_share_a_draw_call import _GLRecorder

    monkeypatch.setattr(vp_mod, "GL", _GLRecorder())
    gpu_share.reset()
    yield
    gpu_share.reset()


def test_what_a_detail_hid_is_not_drawn_inside_a_batch(gl):
    """Alike boxes go up as one mesh. One of them hidden in a detail must
    not come back as part of the run the detail draws."""
    from tests.test_alike_objects_share_a_draw_call import _matrices, _view

    view = _view(12)
    hidden = view.scene.all()[5]
    view._draw_objects(*_matrices(view), hidden_objects=[hidden.id])
    drawn = [key for key, batch in view._batches.items()
             if batch.last_draw == view._batch_draws]
    assert drawn
    assert not any(view._gpu[hidden.id].mesh_key in key for key in drawn)
