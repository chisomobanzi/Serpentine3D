"""A detail can hide objects of its own and leave the model, and every other
detail, as they were.

As in Rhino, inside a detail `hideindetail` hides the objects you pick in
that detail only, `showindetail` brings back all it hid, and
`showselectedindetail` brings back the ones you pick, with them on show
while it asks, the way `showselected` does in the model. A detail could
already leave out whole layers (#38); this is the same for single objects.

A detail keeps them by id beside its hidden layers, so a .serp keeps them.
0.12.2 opens a newer drawing's details and lets a field it does not know
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

NEXT = "0.12.3"


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


def test_what_would_not_appear_anyway_is_not_offered(env):
    """Hidden in the model, or on a layer this detail leaves out: shown
    here, it would still not be seen."""
    scene, sel, hist, ctx, proc = env
    a, b, c, lay, plan, other = _drawing(env)
    walls = scene.layers.create("Walls")
    scene.update(b.id, layer_id=walls.id)
    scene.update(c.id, visible=False)
    plan.hidden_layers = [walls.id]
    plan.hidden_objects = [a.id, b.id, c.id]
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
    w, a, b, plan, other = window
    vp = w.viewport
    drawn = {o.id for o in vp._drawn_objects((), [a.id])}
    assert drawn == {b.id}


def test_inside_a_detail_what_it_hid_cannot_be_picked(window):
    """Nor can what is on a layer it leaves out: neither is there to see."""
    w, a, b, plan, other = window
    vp = w.viewport
    walls = w.scene.layers.create("Walls")
    w.scene.update(b.id, layer_id=walls.id)
    plan.hidden_objects = [a.id]
    plan.hidden_layers = [walls.id]
    vp.layout_view.entered_detail = plan.id
    assert {o.id for o in vp._shown_here()} == set()
    vp.layout_view.entered_detail = other.id
    assert {o.id for o in vp._shown_here()} == {a.id, b.id}


def test_while_a_pick_puts_them_on_show_the_detail_draws_them(window):
    w, a, b, plan, other = window
    vp = w.viewport
    plan.hidden_objects = [a.id]
    vp.layout_view.entered_detail = plan.id
    w.scene.showing_only = frozenset({a.id})
    try:
        assert {o.id for o in vp._drawn_objects((), plan.hidden_objects)} \
            == {a.id}
        assert {o.id for o in vp._shown_here()} == {a.id}
    finally:
        w.scene.showing_only = None


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
    assert plan_back.hidden_objects == [a.id]
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
    assert doc["version"] > 8          # 0.12.2 reads up to version 8
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

