"""A clipping plane can be switched off in some views and left on in others.

Rhino lets a clipping plane choose which views it cuts, and a sheet needs
it: a plan detail cut at sill height, a section detail cut down the
middle, and an elevation not cut at all, each by its own plane, all from
one model. A plane cuts every view to begin with, each model pane and
each detail on every sheet, and can be switched off in any of them: from
the pane's title menu, from the plane's Properties, from the detail's
Properties, or with `disableclippinginview` and `enableclippinginview`
in the view you are working in.

A plane keeps the views it is off in, beside `enabled`, which still
pauses it everywhere at once and leaves those views as they were. A
model pane is named by the view it was made for ("perspective", "top",
"front", "right"), which stays its name when it is turned to another, and
a detail by its id, which a .serp keeps.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import clipping
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.viewport import Viewport, clip_plane_frames


def _plane_rect():
    """A rectangle on the world XY plane that takes away the half above it
    (as in test_a_clipping_plane_caps_what_it_cuts.py)."""
    return g.planar_face(g.make_polyline(
        [(-60, -60, 0), (60, -60, 0), (60, 60, 0), (-60, 60, 0)],
        closed=True))


def _add_plane(scene, name="Clip", **clip):
    obj = scene.add(_plane_rect(), name=name)
    scene.update(obj.id, clip_plane={"enabled": True, **clip})
    return scene.get(obj.id)


# --- the rule ----------------------------------------------------------------

def test_a_plane_cuts_every_view_until_it_is_switched_off_in_one():
    on = {"enabled": True}
    assert clipping.cuts(on, "top") and clipping.cuts(on, "d1")
    off_in_top = {"enabled": True, "off_in": ["top"]}
    assert not clipping.cuts(off_in_top, "top")
    assert clipping.cuts(off_in_top, "perspective")
    assert clipping.cuts(off_in_top, None)      # not asking about one view


def test_a_paused_plane_cuts_no_view_and_keeps_its_views():
    paused = {"enabled": False, "off_in": ["top"]}
    assert not clipping.cuts(paused, "perspective")
    assert not clipping.cuts(paused, None)
    assert not clipping.cuts(None, "top")


def test_switching_a_view_hands_back_a_new_setting():
    on = {"enabled": True}
    off = clipping.switched(on, "top", False)
    assert off == {"enabled": True, "off_in": ["top"]}
    assert on == {"enabled": True}, "the plane's own setting was changed"
    assert clipping.switched(off, "top", False) == off
    both = clipping.switched(off, "d1", False)
    assert both["off_in"] == ["top", "d1"]
    # on in every view again leaves no list behind, so a file written
    # with no plane switched off anywhere is what it was before
    assert clipping.switched(clipping.switched(both, "top", True),
                             "d1", True) == {"enabled": True}
    paused = {"enabled": False, "off_in": ["top"]}
    assert clipping.switched(paused, "top", True) == {"enabled": False}


def test_frames_say_whether_a_plane_cuts_the_view_asked_about():
    scene = Scene()
    _add_plane(scene, off_in=["top"])
    (_o, _n, on), = clip_plane_frames(scene.all(), "top")
    assert not on
    (_o, _n, on), = clip_plane_frames(scene.all(), "perspective")
    assert on
    (_o, _n, on), = clip_plane_frames(scene.all())
    assert on


# --- a pane cuts by its own view, a detail by its own ----------------------

@pytest.fixture
def pane():
    scene = Scene()
    return Viewport(scene, SelectionManager(scene))


def test_a_pane_is_named_for_the_view_it_was_made_for(pane):
    assert pane.view_key == "perspective"
    assert pane.clip_view() == "perspective"
    pane.set_view("top")
    assert pane.clip_view() == "perspective", \
        "turning a pane to another view changed which pane it is"


def test_a_pane_is_cut_only_by_the_planes_on_in_it(pane):
    from serpentine3d.ui.viewport import clip_equation
    keep = _add_plane(pane.scene, "Keep")
    _add_plane(pane.scene, "Off in top", off_in=["top"])
    assert len(pane._clip_vectors()) == 2
    pane.view_key = "top"
    (vec,) = pane._clip_vectors()
    ((origin, normal, _on),) = clip_plane_frames([keep])
    assert np.allclose(vec, clip_equation(origin, normal))


def test_a_detail_is_cut_by_the_planes_on_in_it(pane):
    _add_plane(pane.scene, off_in=["d1"])
    assert len(pane._clip_vectors()) == 1
    with pane._into_detail(400, 300, 1.0, 1.0, 2.0, view="d1"):
        assert pane._clip_vectors() == []
    with pane._into_detail(400, 300, 1.0, 1.0, 2.0, view="d2"):
        assert len(pane._clip_vectors()) == 1
    assert len(pane._clip_vectors()) == 1


def test_a_plane_off_here_draws_its_arrow_faint_here(pane):
    """The arrow is drawn from the same frames as the cut, so a plane
    switched off in a view shows there the way a paused one does."""
    _add_plane(pane.scene, off_in=["perspective"])
    ((_o, _n, on),) = pane._clip_frames()
    assert not on
    ((_o, _n, on),) = pane._clip_frames("top")
    assert on


def test_asking_about_another_view_reads_no_more_geometry(pane, monkeypatch):
    """Planes are read off their geometry once a revision, whichever
    views ask: a sheet asks once for each detail on it, every frame."""
    _add_plane(pane.scene, off_in=["d1"])
    _add_plane(pane.scene, off_in=["d2"])
    normal = g.face_normal
    calls = []

    def counted(face):
        calls.append(1)
        return normal(face)

    monkeypatch.setattr(g, "face_normal", counted)
    for _ in range(3):
        for view in ("perspective", "d1", "d2", "d3"):
            pane._clip_vectors(view)
            pane._clip_frames(view)
    assert len(calls) == 2


def test_the_window_names_its_four_panes(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    try:
        w.set_view_layout("quad")
        keys = {vp.view_key for vp in w.all_viewports()}
        assert keys == {"perspective", "top", "front", "right"}
        extra = w.new_viewport_dock()
        assert extra.view_key not in keys and extra.view_key
    finally:
        w.mark_saved()
        w.close()


# --- a hidden-line detail -----------------------------------------------------

@pytest.fixture
def sheet(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((-20, -20, -20), 40, 40, 40), name="Box")
    plane = _add_plane(w.scene)
    az, el = STANDARD_VIEWS["front"]
    plan = DetailView(x=20, y=40, w=180, h=150, azimuth=az, elevation=el,
                      target=[0.0, 0.0, 0.0], scale_denom=1.0,
                      display_mode="hidden")
    other = DetailView(x=210, y=40, w=180, h=150, azimuth=az, elevation=el,
                       target=[0.0, 0.0, 0.0], scale_denom=1.0,
                       display_mode="hidden")
    lay = Layout(name="Sheet")
    lay.details.extend([plan, other])
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    yield w, lay, plan, other, box.id, plane.id
    w.mark_saved()
    w.close()


def _top_of_box(lv, det, box_id) -> float:
    pts = [p for oid, _lt, polys in lv._detail_hlr(det)["visible_by_obj"]
           if oid == box_id for poly in polys for p in poly]
    assert pts, "the box drew nothing, so the test proves nothing"
    return float(np.asarray(pts, float)[:, 1].max())


def test_a_hidden_line_detail_switched_off_draws_whole(sheet):
    w, lay, plan, other, box_id, plane_id = sheet
    lv = w.viewport.layout_view
    assert _top_of_box(lv, plan, box_id) == pytest.approx(0.0, abs=1e-6)

    assert clipping.switch(w.scene, plane_id, plan.id, False)
    assert _top_of_box(lv, plan, box_id) == pytest.approx(20.0)
    assert lv._detail_hlr(plan)["cut_by_obj"] == []
    assert _top_of_box(lv, other, box_id) == pytest.approx(0.0, abs=1e-6), \
        "switching the plane off in one detail took it out of another"


# --- commands -----------------------------------------------------------------

def _here(ctx, key):
    """Put the command in a model pane called `key`."""
    from tests.conftest import StubViewport

    class Pane(StubViewport):
        def clip_view(self):
            return key

    ctx.viewport = Pane("model")


def test_disabling_in_this_view_leaves_the_others_cut(env):
    scene, sel, hist, ctx, proc = env
    plane = _add_plane(scene)
    _here(ctx, "top")
    sel.set([plane.id])
    proc.run("disableclippinginview")
    assert not proc.busy
    cp = scene.get(plane.id).clip_plane
    assert cp == {"enabled": True, "off_in": ["top"]}

    _here(ctx, "perspective")
    sel.set([plane.id])
    proc.run("ecv")                       # in a view it was never off in
    assert scene.get(plane.id).clip_plane == cp
    _here(ctx, "top")
    sel.set([plane.id])
    proc.run("enableclippinginview")
    assert scene.get(plane.id).clip_plane == {"enabled": True}


def test_enter_switches_every_plane_in_this_view(env):
    scene, sel, hist, ctx, proc = env
    a = _add_plane(scene, "A")
    b = _add_plane(scene, "B")
    _here(ctx, "d1")
    proc.run("dcv")
    proc.provide_text("")                 # Enter: all of them
    assert not proc.busy
    assert all(scene.get(o.id).clip_plane["off_in"] == ["d1"]
               for o in (a, b))


def test_enabling_a_paused_plane_in_this_view_resumes_it(env):
    """A paused plane cuts no view, so turning it on in this one has to
    resume it, and it says so: it cuts its other views again as well."""
    scene, sel, hist, ctx, proc = env
    plane = _add_plane(scene, off_in=["top"])
    scene.update(plane.id, clip_plane={**scene.get(plane.id).clip_plane,
                                       "enabled": False})
    said = []
    ctx.add_echo_listener(said.append)
    _here(ctx, "top")
    sel.set([plane.id])
    proc.run("ecv")
    assert scene.get(plane.id).clip_plane == {"enabled": True}
    assert any("paused" in line for line in said)


def test_pausing_and_resuming_keeps_the_views(env):
    scene, sel, hist, ctx, proc = env
    plane = _add_plane(scene, off_in=["top", "d1"])
    sel.set([plane.id])
    proc.run("disableclippingplane")
    assert scene.get(plane.id).clip_plane == {"enabled": False,
                                              "off_in": ["top", "d1"]}
    sel.set([plane.id])
    proc.run("enableclippingplane")
    assert scene.get(plane.id).clip_plane == {"enabled": True,
                                              "off_in": ["top", "d1"]}


def test_bare_paper_is_no_view_to_switch_a_plane_in(env):
    scene, sel, hist, ctx, proc = env
    plane = _add_plane(scene)
    said = []
    ctx.add_echo_listener(said.append)
    _here(ctx, None)
    sel.set([plane.id])
    proc.run("dcv")
    assert scene.get(plane.id).clip_plane == {"enabled": True}
    assert any("detail" in line for line in said)


def test_a_pane_inside_a_detail_means_the_detail(pane):
    lay = Layout(name="Sheet")
    det = DetailView()
    lay.details.append(det)
    pane.scene.layouts.append(lay)
    pane.set_space(lay.id)
    assert pane.clip_view() is None, "bare paper is no view"
    pane.layout_view.entered_detail = det.id
    assert pane.clip_view() == det.id


# --- the pane's menu ------------------------------------------------------------

@pytest.fixture
def window(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    yield w
    w.mark_saved()
    w.close()


def _clip_menu(w, vp):
    menu = w._viewport_menu(vp)
    for act in menu.actions():
        if act.menu() is not None and act.text() == "Clipping Planes":
            return act.menu()
    return None


def test_a_pane_menu_lists_the_planes_that_cut_it(window):
    w = window
    vp = w.viewport
    assert _clip_menu(w, vp) is None, "a menu for planes there are none of"
    a = _add_plane(w.scene, "Section A")
    b = _add_plane(w.scene, "Section B", off_in=["perspective"])
    w.scene.update(b.id, clip_plane={**w.scene.get(b.id).clip_plane,
                                     "enabled": False})
    acts = _clip_menu(w, vp).actions()
    assert [x.text() for x in acts] == ["Section A", "Section B (paused)"]
    assert [x.isChecked() for x in acts] == [True, False]
    assert all(x.isCheckable() for x in acts)

    acts[0].trigger()
    assert w.scene.get(a.id).clip_plane["off_in"] == ["perspective"]
    w.history.undo()
    assert w.scene.get(a.id).clip_plane == {"enabled": True}


# --- Properties -------------------------------------------------------------------

def test_a_plane_lists_the_views_it_cuts(window):
    w = window
    w.set_view_layout("quad")
    plane = _add_plane(w.scene, off_in=["top"])
    lay = Layout(name="Sheet")
    det = DetailView(x=20, y=40, w=180, h=150, scale_denom=50.0)
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.scene.notify()
    w.selection.set([plane.id])
    QApplication.processEvents()
    props = w.properties
    assert props.form.isRowVisible(props.clip_views)
    views = props.clip_views.views()
    keys = [key for key, _label, _on in views]
    assert set(keys[:4]) == {"perspective", "top", "front", "right"}
    assert keys[4:] == [det.id]
    assert {key: on for key, _l, on in views}["top"] is False
    assert all(on for key, _l, on in views if key != "top")
    assert props.clip_views.sheets() == ["Sheet"]

    props.clip_views.set_view(det.id, False)
    assert w.scene.get(plane.id).clip_plane["off_in"] == ["top", det.id]
    props.clip_views.set_view("top", True)
    assert w.scene.get(plane.id).clip_plane["off_in"] == [det.id]
    w.history.undo()
    assert w.scene.get(plane.id).clip_plane["off_in"] == ["top", det.id]


def test_a_plane_can_be_paused_from_its_properties(window):
    w = window
    plane = _add_plane(w.scene, off_in=["top"])
    w.selection.set([plane.id])
    QApplication.processEvents()
    clip_views = w.properties.clip_views
    assert clip_views.cutting()
    clip_views.set_cutting(False)
    assert w.scene.get(plane.id).clip_plane == {"enabled": False,
                                                "off_in": ["top"]}
    QApplication.processEvents()
    assert not w.properties.clip_views.cutting()
    assert not w.properties.clip_views.views_enabled()


def test_only_a_clipping_plane_has_the_row(window):
    w = window
    box = w.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    w.selection.set([box.id])
    QApplication.processEvents()
    assert not w.properties.form.isRowVisible(w.properties.clip_views)


def _pick_detail(w, lay, det):
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.selected = [("detail", det)]
    w.viewport.layoutSelectionChanged.emit()
    QApplication.processEvents()


def test_a_detail_lists_the_planes_that_cut_it(window):
    w = window
    a = _add_plane(w.scene, "Section A")
    b = _add_plane(w.scene, "Section B")
    lay = Layout(name="Sheet")
    det = DetailView(x=20, y=40, w=180, h=150)
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.scene.update(b.id, clip_plane={"enabled": True, "off_in": [det.id]})
    _pick_detail(w, lay, det)
    props = w.properties
    assert props.form.isRowVisible(props.detail_clips)
    assert props.detail_clips.planes() == [("Section A", True),
                                           ("Section B", False)]
    props.detail_clips.set_plane(a.id, False)
    assert w.scene.get(a.id).clip_plane["off_in"] == [det.id]
    w.history.undo()
    assert w.scene.get(a.id).clip_plane == {"enabled": True}


def test_a_detail_with_no_planes_to_list_has_no_row(window):
    w = window
    lay = Layout(name="Sheet")
    det = DetailView(x=20, y=40, w=180, h=150)
    lay.details.append(det)
    w.scene.layouts.append(lay)
    _pick_detail(w, lay, det)
    assert not w.properties.form.isRowVisible(w.properties.detail_clips)


# --- what carries a view's setting along -------------------------------------------

def test_a_duplicated_sheet_keeps_its_details_planes(window):
    w = window
    plane = _add_plane(w.scene)
    lay = Layout(name="Sheet")
    det = DetailView(x=20, y=40, w=180, h=150)
    lay.details.append(det)
    w.scene.layouts.append(lay)
    clipping.switch(w.scene, plane.id, det.id, False)
    dup = w.duplicate_layout(lay)
    new = dup.details[0]
    assert new.id != det.id
    assert w.scene.get(plane.id).clip_plane["off_in"] == [det.id, new.id]


def test_the_layout_command_duplicates_them_too(env):
    scene, sel, hist, ctx, proc = env
    plane = _add_plane(scene)
    lay = Layout(name="Sheet")
    det = DetailView()
    lay.details.append(det)
    scene.layouts.append(lay)
    clipping.switch(scene, plane.id, det.id, False)
    proc.run("layout")
    for answer in ("Duplicate", "Sheet"):
        proc.provide_text(answer)
    assert not proc.busy
    new = scene.layouts[-1].details[0]
    assert scene.get(plane.id).clip_plane["off_in"] == [det.id, new.id]


def test_a_file_keeps_which_views_a_plane_is_off_in(tmp_path):
    from serpentine3d.fileio import native
    scene = Scene()
    plane = _add_plane(scene, off_in=["top", "d1"])
    path = str(tmp_path / "views.serp")
    native.save_scene(scene, path)
    back = Scene()
    native.load_scene(back, path)
    (obj,) = [o for o in back.all() if o.clip_plane]
    assert obj.clip_plane == {"enabled": True, "off_in": ["top", "d1"]}
    assert plane.clip_plane == obj.clip_plane


def test_scripts_can_read_which_views_a_plane_is_off_in(window):
    from serpentine3d.api import SerpApi
    w = window
    _add_plane(w.scene, "Section", off_in=["top"])
    api = SerpApi(w)
    (row,) = [r for r in api.scene_info()["objects"] if r["name"] == "Section"]
    assert row["clip_plane"] == {"enabled": True, "off_in": ["top"]}


def test_enter_on_nothing_pauses_every_plane_as_the_prompt_says(env):
    """'Enter or all = all', the prompt says, but Enter on nothing used to
    cancel the command instead."""
    scene, sel, hist, ctx, proc = env
    a = _add_plane(scene, "A")
    b = _add_plane(scene, "B")
    proc.run("disableclippingplane")
    proc.provide_text("")
    assert not proc.busy
    assert not any(scene.get(o.id).clip_plane["enabled"] for o in (a, b))
