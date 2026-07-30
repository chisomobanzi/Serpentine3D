"""Gold in a hidden-line detail.

A hidden-line detail is line work and nothing else. It is not drawn from the
model each frame the way a wireframe or shaded detail is — it is one hidden-line
pass, cached, and the result was a single heap of polylines with nothing in it
to say which object each came from. So an object picked through such a detail
was selected everywhere in the document except in the frame you picked it in.

The pass already splits its visible edges per shape, to keep each object's
linetype. Carrying the object's own name out with them as well is enough: the
ink is decided at paint time, so picking something does not redo the pass.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout
from serpentine3d.ui import theme
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.layout_view import LINE_VISIBLE, hlr_visible_segments

GOLD = (*theme.SELECTION_COLOR, 1.0)


@pytest.fixture
def hidden_sheet():
    """Two boxes side by side in one hidden-line detail."""
    w = MainWindow()
    w.resize(1200, 800)
    left = w.scene.add(g.make_box((-60.0, -20.0, 0.0), 40.0, 40.0, 40.0))
    right = w.scene.add(g.make_box((20.0, -20.0, 0.0), 40.0, 40.0, 40.0))
    lay = Layout(name="Sheet1")
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=40.0, y=60.0, w=200.0, h=150.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 20.0], scale_denom=2.0,
                     display_mode="hidden")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, det, left, right


# -- what the pass carries out -------------------------------------------------

def test_the_line_work_says_which_object_it_came_from(hidden_sheet):
    _w, lv, det, left, right = hidden_sheet
    data = lv._detail_hlr(det)
    ids = [oid for oid, _lt, polys in data["visible_by_obj"] if polys]
    assert sorted(ids) == sorted([left.id, right.id])


def test_the_flat_list_still_holds_all_of_it(hidden_sheet):
    """Print and export read `visible`, and a print has no selection in it."""
    _w, lv, det, _left, _right = hidden_sheet
    data = lv._detail_hlr(det)
    per_object = sum(len(polys) for _oid, name, polys
                     in data["visible_by_obj"] if name == "Continuous")
    assert per_object == len(data["visible"])
    assert per_object > 0


def test_an_objects_linetype_comes_with_it(hidden_sheet):
    w, lv, det, left, right = hidden_sheet
    w.scene.update(right.id, linetype="Dashed")
    data = lv._detail_hlr(det)
    names = {oid: name for oid, name, _p in data["visible_by_obj"]}
    assert names[right.id] == "Dashed"
    assert names[left.id] == "Continuous"
    # and the flat lists the exporters read still split the same way
    assert [n for n, _p in data["visible_lt"]] == ["Dashed"]


def test_picking_does_not_redo_the_hidden_line_pass(hidden_sheet):
    """The expensive part does not depend on what is picked, so it is kept."""
    w, lv, det, left, _right = hidden_sheet
    first = lv._detail_hlr(det)
    w.selection.set([left.id])
    assert lv._detail_hlr(det) is first


# -- what ink it is drawn with -------------------------------------------------

def _flat(poly2d):
    """A stand-in for the paper transform: 2D in, 3D out."""
    out = np.zeros((len(poly2d), 3), np.float32)
    out[:, :2] = poly2d
    return out


def _polys(*pts):
    return [np.asarray(pts, np.float32)]


def test_nothing_picked_is_all_one_ink():
    by_obj = [("a", "Continuous", _polys((0, 0), (10, 0))),
              ("b", "Continuous", _polys((0, 5), (10, 5)))]
    groups = hlr_visible_segments(by_obj, _flat, lambda _oid: False)
    assert [ink for ink, _segs in groups] == [LINE_VISIBLE]
    assert len(groups[0][1]) == 2          # one segment from each object


def test_what_is_picked_goes_gold():
    by_obj = [("a", "Continuous", _polys((0, 0), (10, 0))),
              ("b", "Continuous", _polys((0, 5), (10, 5)))]
    groups = hlr_visible_segments(by_obj, _flat, lambda oid: oid == "b")
    inks = {ink: segs for ink, segs in groups}
    assert set(inks) == {LINE_VISIBLE, GOLD}
    assert np.allclose(inks[GOLD][0][0][:2], (0, 5))


def test_gold_is_drawn_last():
    """Two objects sharing an edge: the picked one is the one you see."""
    by_obj = [("a", "Continuous", _polys((0, 0), (10, 0))),
              ("b", "Continuous", _polys((0, 0), (10, 0)))]
    groups = hlr_visible_segments(by_obj, _flat, lambda oid: oid == "b")
    assert [ink for ink, _segs in groups] == [LINE_VISIBLE, GOLD]


def test_a_dashed_object_is_still_dashed_when_it_is_picked():
    by_obj = [("a", "Dashed", _polys((0.0, 0.0), (100.0, 0.0)))]
    groups = hlr_visible_segments(by_obj, _flat, lambda _oid: True)
    (ink, segs), = groups
    assert ink == GOLD
    assert len(segs) > 1                   # broken into dashes, not one line


def test_an_object_with_no_line_work_is_no_group():
    assert hlr_visible_segments([("a", "Continuous", [])], _flat,
                                lambda _oid: False) == []


def test_the_detail_draws_what_the_grouping_gives_it():
    """The paint path is GL, so read it rather than run it."""
    import inspect

    from serpentine3d.ui.layout_view import LayoutView
    src = inspect.getsource(LayoutView._paint_detail_hlr)
    assert "hlr_visible_segments" in src
    assert "visible_by_obj" in src
    # the old two-pass drawing of `visible` then `visible_lt` is gone
    assert "data[\"visible\"]" not in src
