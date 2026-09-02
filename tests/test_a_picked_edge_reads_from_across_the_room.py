"""A picked edge is drawn wide enough to actually see.

Lourenço reported no feedback when picking edges. The highlight was
there all along — gold, "3 pixels" wide — but it asked glLineWidth for
those pixels, and plenty of drivers cap lines at 1: the pick came back
as one gold hairline over a gold-selected object. The object edges
already solved this with the screen-space quad shader; the highlight
now goes through the same pipeline, gold over a dark halo like the
control-point markers, so it is honest pixels on every driver.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from tests.test_viewport_perf import _FakeGpu, _GLRecorder

pytest.importorskip("PySide6")

FAR = np.array([500000.0, 300000.0, 0.0])


class _Bucket:
    def __init__(self):
        self.uploads = []
        self.vao = 1
        self.count = 0

    def update(self, segments):
        self.uploads.append(np.asarray(segments, float))
        self.count = len(segments) * 6


@pytest.fixture
def rig(monkeypatch):
    rec = _GLRecorder()
    monkeypatch.setattr(vp_mod, "GL", rec)
    scene = Scene()
    sel = SelectionManager(scene)
    view = vp_mod.Viewport(scene, sel)
    view.resize(1200, 800)
    view._mesh_prog, view._line_prog, view._thick_prog = 11, 12, 13
    view._max_line_width = 1.0          # the capped-driver case
    view._preview = _Bucket()
    view._preview_thick = _Bucket()
    obj = scene.add(g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]))
    view._gpu[obj.id] = _FakeGpu(mesh_key=obj.mesh.uid, tris=0)
    return rec, view, obj


def _mvp(view):
    w, h = view.width(), view.height()
    v = view.camera.view_matrix()
    return view.camera.proj_matrix(w, h) @ v, v


def test_a_picked_edge_goes_through_the_thick_pipeline(rig):
    rec, view, obj = rig
    view.selection.toggle_subobject(obj.id, "edge", 0)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    assert view._preview_thick.uploads, \
        "the highlight still asks glLineWidth for pixels the driver caps"


def test_the_highlight_is_gold_over_a_dark_halo(rig):
    """Two passes, so the pick reads on a pale face and on the dark
    background alike — the control-point markers' trick."""
    rec, view, obj = rig
    view.selection.toggle_subobject(obj.id, "edge", 0)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    # the only indexed draws in this scene are the highlight's passes:
    # the object itself is a hairline through glDrawArrays
    assert rec.n("glDrawElements") == 2, (
        f"{rec.n('glDrawElements')} indexed draws — expected halo + gold")


def test_no_pick_no_thick_draws(rig):
    rec, view, obj = rig
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    assert not view._preview_thick.uploads
    assert rec.n("glDrawElements") == 0


def test_the_highlight_rides_the_mesh_anchor(rig):
    """A picked edge on far geometry holds as still as the geometry."""
    rec, view, obj = rig
    seg = np.array([[[0.0, 0, 0], [10.0, 0, 0]]]) + FAR
    obj.mesh.edge_segments = seg
    obj.mesh.vertices = seg.reshape(-1, 3)    # bounds follow, or the
    view.camera.target = FAR.copy()           # cull throws the pick out
    view.camera.distance = 40.0
    view._gpu[obj.id].anchor = FAR.copy()
    view.selection.toggle_subobject(obj.id, "edge", 0)
    mvp, v = _mvp(view)
    view._draw_objects(mvp, v)
    worst = max(float(np.abs(u).max())
                for u in view._preview_thick.uploads)
    assert worst < 1000.0, \
        f"highlight uploaded absolute coordinates ({worst:.0f})"


def test_the_width_is_worth_calling_feedback():
    assert vp_mod.EDGE_PICK_PX >= 4.0
    assert vp_mod.EDGE_PICK_HALO_PX > vp_mod.EDGE_PICK_PX


def test_details_on_sheets_share_the_same_highlight():
    """One draw loop serves the model and every detail, so the fix does
    not need repeating anywhere."""
    src = inspect.getsource(vp_mod.Viewport._draw_objects)
    assert "_draw_thick_segments(" in src
    assert "glLineWidth(3.0)" not in src
