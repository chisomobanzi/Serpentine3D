"""Zoom Selected frames what you are holding, even when it is a point.

Pick a control point and ask for Zoom Selected, and the command said
"Nothing selected": the selection's ids are whole objects, and a held
control point, edge or face lives in `subobjects`, which nobody asked.
What you are holding is what you meant to frame.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager

pytest.importorskip("PySide6")

TIP = (60.0, 40.0, 20.0)


@pytest.fixture
def view():
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    vp.resize(1600, 900)
    return vp


def _curve(view):
    return view.scene.add(g.make_polyline([(0.0, 0.0, 0.0), TIP]))


def _hold_cv(view, obj, index=1):
    view.cv_enabled.add(obj.id)
    view.selection.toggle_subobject(obj.id, "cv", index)


# -- control points -------------------------------------------------------

def test_a_held_control_point_is_something_to_zoom_to(view):
    _hold_cv(view, _curve(view))
    assert view.zoom_selected(), "a held point counted as nothing"
    assert np.allclose(view.camera.target, TIP, atol=1e-6)


def test_zooming_one_point_still_stands_somewhere_sensible(view):
    """A point has no size to fill the frame with; the camera must not
    land on top of it or at nan."""
    _hold_cv(view, _curve(view))
    view.zoom_selected()
    assert np.isfinite(view.camera.distance)
    assert view.camera.distance > 0.1


def test_a_point_nobody_can_see_is_not_held(view):
    """PointsOff leaves the selection as it found it, and the gumball
    ignores those entries; zoom follows the same rule."""
    obj = _curve(view)
    view.selection.toggle_subobject(obj.id, "cv", 1)   # points not shown
    assert not view.zoom_selected()


def test_nothing_held_is_still_nothing(view):
    _curve(view)
    assert not view.zoom_selected()


# -- edges and faces ------------------------------------------------------

def test_a_picked_edge_frames_that_edge(view):
    box = view.scene.add(g.make_box((0, 0, 0), 10.0, 10.0, 10.0))
    edge = int(box.mesh.edge_of_segment[0])
    view.selection.toggle_subobject(box.id, "edge", edge)
    assert view.zoom_selected()
    segs = box.mesh.edge_segments[box.mesh.edge_of_segment == edge]
    pts = segs.reshape(-1, 3)
    middle = (pts.min(axis=0) + pts.max(axis=0)) / 2
    assert np.allclose(view.camera.target, middle, atol=1e-4)


def test_a_picked_face_frames_that_face(view):
    box = view.scene.add(g.make_box((0, 0, 0), 10.0, 10.0, 10.0))
    face = int(box.mesh.face_of_triangle[0])
    view.selection.toggle_subobject(box.id, "face", face)
    assert view.zoom_selected()
    tris = box.mesh.triangles[box.mesh.face_of_triangle == face]
    pts = box.mesh.vertices[tris.ravel()]
    middle = (pts.min(axis=0) + pts.max(axis=0)) / 2
    assert np.allclose(view.camera.target, middle, atol=1e-4)
    assert not np.allclose(view.camera.target, (5.0, 5.0, 5.0),
                           atol=1e-3), "framed the whole box, not the face"


# -- mixtures -------------------------------------------------------------

def test_an_object_and_a_held_point_are_framed_together(view):
    """Shift-picking adds to a selection; zoom frames all of it."""
    far = view.scene.add(g.make_box((100, 100, 100), 2.0, 2.0, 2.0))
    view.selection.set([far.id])
    _hold_cv(view, _curve(view))     # a shift-pick keeps the box selected
    assert view.zoom_selected()
    lo = np.minimum(TIP, (100.0, 100.0, 100.0))
    hi = np.maximum(TIP, (102.0, 102.0, 102.0))
    assert np.allclose(view.camera.target, (lo + hi) / 2, atol=1e-4)


# -- the command opens on it ----------------------------------------------

def test_zoom_offers_selected_when_only_a_point_is_held(env):
    scene, sel, _hist, ctx, proc = env
    obj = scene.add(g.make_polyline([(0.0, 0.0, 0.0), TIP]))
    sel.toggle_subobject(obj.id, "cv", 1)
    proc.run("zoom")
    assert proc.request.default == "Selected"
