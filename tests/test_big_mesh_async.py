"""A survey scan is not "instant" just because it arrived as a mesh.

The viewport already keeps heavy tessellation off the thread that draws:
a shape with enough faces gets a bounding box to stand in for it and is
built on a worker. Meshes skipped that check entirely, on the grounds that
they convert instantly — which is true of the couple of hundred small ones
in a drawing and badly false of a survey scan.

Arriving as a mesh does not mean arriving ready to draw. The shading is
worked out from the geometry, because reading Rhino's own normals costs
36us each and 239 s for one of these objects, and welding and shading 6.6
million vertices takes about ten seconds. On the cave file two such scans
between them held 13.2M of 16.8M vertices and accounted for 26 s of the 29
that the window spent frozen after the file had already finished opening.
"""

import numpy as np
import pytest

from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _viewport(scene):
    _qapp()
    from serpentine3d.ui.viewport import Viewport
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    return vp


def _grid(side: int) -> MeshShape:
    """A side x side sheet of quads, as a mesh with no normals.

    No normals on purpose: that is how one comes out of the .3dm importer,
    and it is what makes the display build expensive.
    """
    xs, ys = np.meshgrid(np.arange(side, dtype=float),
                         np.arange(side, dtype=float))
    verts = np.column_stack([xs.ravel(), ys.ravel(),
                             np.zeros(side * side)])
    idx = np.arange(side * side).reshape(side, side)
    a = idx[:-1, :-1].ravel()
    b = idx[:-1, 1:].ravel()
    c = idx[1:, 1:].ravel()
    d = idx[1:, :-1].ravel()
    tris = np.concatenate([np.column_stack([a, b, c]),
                           np.column_stack([a, c, d])])
    return MeshShape(verts, tris.astype(np.uint32))


def test_a_big_mesh_is_built_off_the_drawing_thread():
    scene = Scene()
    vp = _viewport(scene)
    big = _grid(400)                       # 160k vertices
    assert len(big.vertices) >= vp.ASYNC_MESH_VERTICES
    obj = scene.add(big, name="Survey")
    assert vp._schedule_tess(obj) is True
    assert obj.id in vp._tess_pending, "no placeholder while it is built"


def test_a_small_mesh_still_goes_straight_through():
    """Most of a drawing's meshes are small, and a round trip through the
    pool costs more than building them — plus a box would flash where the
    object should already be."""
    scene = Scene()
    vp = _viewport(scene)
    small = _grid(20)                      # 400 vertices
    assert len(small.vertices) < vp.ASYNC_MESH_VERTICES
    obj = scene.add(small, name="Bracket")
    assert vp._schedule_tess(obj) is False
    assert obj.id not in vp._tess_pending


def test_the_placeholder_is_the_meshs_own_bounding_box():
    """The stand-in has to sit where the object does, or the scene jumps
    when the real thing lands."""
    scene = Scene()
    vp = _viewport(scene)
    obj = scene.add(_grid(400), name="Survey")
    vp._schedule_tess(obj)
    segs = np.asarray(vp._tess_pending[obj.id], float).reshape(-1, 3)
    mn, mx = obj.shape.bbox()
    assert np.allclose(segs.min(axis=0), mn)
    assert np.allclose(segs.max(axis=0), mx)


def test_the_work_actually_happens():
    """Deferring it is only an improvement if it still gets done."""
    scene = Scene()
    vp = _viewport(scene)
    obj = scene.add(_grid(400), name="Survey")
    assert vp._schedule_tess(obj) is True
    vp._worker_pool().shutdown(wait=True)
    vp._tess_pool = None
    assert obj.mesh_ready, "the deferred mesh was never built"


def test_asking_twice_does_not_queue_it_twice():
    scene = Scene()
    vp = _viewport(scene)
    obj = scene.add(_grid(400), name="Survey")
    assert vp._schedule_tess(obj) is True
    assert vp._schedule_tess(obj) is True
    vp._worker_pool().shutdown(wait=True)
    vp._tess_pool = None


@pytest.mark.parametrize("bad", [MeshShape(np.zeros((0, 3)),
                                           np.zeros((0, 3), np.uint32))])
def test_an_empty_mesh_is_not_deferred(bad):
    """Nothing to draw and nothing to build; a box round it would be a box
    round the origin."""
    scene = Scene()
    vp = _viewport(scene)
    obj = scene.add(bad, name="Empty")
    assert vp._schedule_tess(obj) is False
