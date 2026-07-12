"""Performance infrastructure: notify kinds, threaded meshing, pick culling."""

import threading
import time

import numpy as np
import pytest

from serpentine.core import geometry as g
from serpentine.core.scene import Scene


def test_notify_kinds():
    scene = Scene()
    calls = {"all": 0, "objects": 0}
    scene.add_listener(lambda: calls.__setitem__("all", calls["all"] + 1))
    scene.add_listener(
        lambda: calls.__setitem__("objects", calls["objects"] + 1),
        kinds=("objects", "layers"))
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))          # kind="objects"
    assert calls == {"all": 1, "objects": 1}
    scene.notify("layouts")                            # sheet drag etc.
    assert calls == {"all": 2, "objects": 1}
    scene.notify()                                     # "all" reaches everyone
    assert calls == {"all": 3, "objects": 2}


def test_concurrent_mesh_access_tessellates_once(monkeypatch):
    """obj.mesh is safe to race: one tessellation, everyone gets it."""
    import serpentine.core.scene as scene_mod
    real = scene_mod.tessellate
    calls = []

    def counting(shape, *a, **kw):
        calls.append(1)
        time.sleep(0.05)                # widen the race window
        return real(shape, *a, **kw)

    monkeypatch.setattr(scene_mod, "tessellate", counting)
    scene = Scene()
    obj = scene.add(g.make_sphere((0, 0, 0), 5))
    results = []
    threads = [threading.Thread(target=lambda: results.append(obj.mesh))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert all(r is results[0] for r in results)
    assert results[0].has_faces


def test_display_mesh_bounds_cached():
    from serpentine.core.tessellate import tessellate
    box = g.make_box((1, 2, 3), 2, 2, 2)
    dm = tessellate(box)
    b1 = dm.bounds()
    assert np.allclose(b1[0], (1, 2, 3), atol=1e-6)
    assert np.allclose(b1[1], (3, 4, 5), atol=1e-6)
    assert dm.bounds() is b1                # cached


def test_layer_lineweight_roundtrip(tmp_path):
    from serpentine import fileio
    scene = Scene()
    heavy = scene.layers.create("Walls")
    scene.layers.set_lineweight(heavy.id, 3.0)
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), layer_id=heavy.id)
    path = str(tmp_path / "weights.serp")
    fileio.export_file(scene, path)
    loaded = Scene()
    fileio.import_file(loaded, path)
    walls = loaded.layers.find_by_name("Walls")
    assert walls.lineweight == pytest.approx(3.0)


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_pick_reject_culls_offscreen_objects():
    _qapp()
    from serpentine.core.selection import SelectionManager
    from serpentine.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    vp.resize(800, 600)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 50.0
    near = scene.add(g.make_box((-2, -2, -2), 4, 4, 4))
    far = scene.add(g.make_box((500, 500, 0), 4, 4, 4))
    w, h = vp.width(), vp.height()
    # centre pixel: the origin box must survive, the distant one is culled
    assert not vp._pick_reject(near.mesh, 390, 290, 410, 310, w, h)
    assert vp._pick_reject(far.mesh, 390, 290, 410, 310, w, h)


def test_background_tessellation_of_heavy_shapes():
    _qapp()
    from serpentine.core.selection import SelectionManager
    from serpentine.ui.viewport import Viewport
    scene = Scene()
    sel = SelectionManager(scene)
    vp = Viewport(scene, sel)
    # 8 boxes = 48 faces: crosses ASYNC_FACE_COUNT
    shapes = [g.make_box((i * 3.0, j * 3.0, k * 3.0), 2, 2, 2)
              for i in range(2) for j in range(2) for k in range(2)]
    obj = scene.add(g.make_compound(shapes))
    assert not obj.mesh_ready
    assert vp._schedule_tess(obj)           # queued with a bbox placeholder
    assert obj.id in vp._tess_pending
    assert len(vp._tess_pending[obj.id]) == 24      # 12 AABB edges
    deadline = time.time() + 10
    while not obj.mesh_ready and time.time() < deadline:
        time.sleep(0.01)
    assert obj.mesh_ready, "background tessellation never finished"
    assert obj.mesh.has_faces
    # a small shape stays on the synchronous path
    small = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    assert not vp._schedule_tess(small)
