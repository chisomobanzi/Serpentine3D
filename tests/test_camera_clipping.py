"""Clipping planes follow the scene, not just the zoom (GitHub #5).

Zooming in on a detail used to clip everything else away: `far` was
`distance * 100 + 1000`, so getting close to a small part collapsed the
far plane to a bubble around it and the rest of the model vanished —
"exclusion", as the report put it through translation. The near plane's
absolute 0.01 floor and zoom's 0.01 distance clamp meant a millimetre-scale
detail could never fill the frame at all.
"""

import numpy as np
import pytest

from serpentine3d.ui.camera import Camera


def _camera_at(distance: float, bounds=None) -> Camera:
    cam = Camera()
    cam.distance = distance
    if bounds is not None:
        cam.scene_bounds = bounds
    return cam


# A survey-sized model: 50 metres across in millimetres, like the cave file.
BIG = ((0.0, 0.0, 0.0), (50_000.0, 50_000.0, 20_000.0))


def test_far_plane_encloses_scene_when_zoomed_close():
    cam = _camera_at(2.0, bounds=BIG)
    cam.target = np.array([100.0, 100.0, 100.0])
    _near, far = cam.clip_planes()
    farthest = max(np.linalg.norm(np.array(corner, float) - cam.position)
                   for corner in [(x, y, z)
                                  for x in (0, 50_000.0)
                                  for y in (0, 50_000.0)
                                  for z in (0, 20_000.0)])
    assert far >= farthest


def test_near_plane_shrinks_below_old_floor_when_close():
    # A small model seen from very close: the old 0.01 floor clipped the
    # front of the detail before it filled the frame.
    small = ((0.0, 0.0, 0.0), (5.0, 5.0, 5.0))
    cam = _camera_at(0.05, bounds=small)
    near, _far = cam.clip_planes()
    assert near < 0.01


def test_near_far_ratio_bounded_for_depth_precision():
    cam = _camera_at(0.5, bounds=BIG)
    near, far = cam.clip_planes()
    assert far / near <= 2e6


def test_planes_ordered_and_positive_in_perspective():
    for distance in (0.001, 1.0, 1e5):
        for bounds in (None, BIG):
            cam = _camera_at(distance, bounds=bounds)
            near, far = cam.clip_planes()
            assert 0 < near < far


def test_no_bounds_matches_old_behaviour():
    cam = _camera_at(60.0)
    near, far = cam.clip_planes()
    assert near == pytest.approx(0.06)
    assert far == pytest.approx(60.0 * 100.0 + 1000.0)


def test_parallel_slab_covers_scene():
    cam = _camera_at(3.0, bounds=BIG)
    cam.projection = "parallel"
    near, far = cam.clip_planes()
    fwd = (cam.target - cam.position)
    fwd = fwd / np.linalg.norm(fwd)
    depths = [float((np.array(c, float) - cam.position) @ fwd)
              for c in [(x, y, z)
                        for x in (0, 50_000.0)
                        for y in (0, 50_000.0)
                        for z in (0, 20_000.0)]]
    assert near <= min(depths)
    assert far >= max(depths)


def test_proj_matrix_uses_scene_planes():
    # The projection actually built must move when the scene bounds do —
    # including through the cached view-projection used by picking.
    cam = _camera_at(2.0)
    before = cam.proj_matrix(800, 600).copy()
    vp_before = cam._view_proj(800, 600)[0].copy()
    cam.scene_bounds = BIG
    after = cam.proj_matrix(800, 600)
    vp_after = cam._view_proj(800, 600)[0]
    assert not np.allclose(before, after)
    assert not np.allclose(vp_before, vp_after)


def test_zoom_reaches_below_old_clamp():
    cam = _camera_at(0.02)
    cam.zoom(10.0)
    assert cam.distance < 0.01
    cam.zoom(-1000.0)
    assert np.isfinite(cam.distance)


# -- viewport wiring ---------------------------------------------------------
# The draw path itself cannot run under offscreen pytest (no GL), so the
# helper is exercised directly and paintGL is only checked by source.

def _viewport():
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    return Viewport(scene, SelectionManager(scene)), scene


def test_viewport_hands_scene_bounds_to_camera():
    from serpentine3d.core.mesh import MeshShape
    vp, scene = _viewport()
    tri = MeshShape(np.array([[0.0, 0, 0], [900.0, 0, 0], [0, 900.0, 0]]),
                    np.array([[0, 1, 2]], np.uint32))
    scene.add(tri, name="far corner")
    vp._refresh_camera_bounds()
    mn, mx = vp.camera.scene_bounds
    assert mx[0] >= 900.0 and mx[1] >= 900.0
    # the grid is drawn with the same projection, so its extent counts too
    assert mn[0] <= -vp._grid_params[0]


def test_viewport_bounds_cache_follows_revision():
    from serpentine3d.core.mesh import MeshShape
    vp, scene = _viewport()
    vp._refresh_camera_bounds()
    first = vp.camera.scene_bounds
    tri = MeshShape(np.array([[0.0, 0, 0], [5000.0, 0, 0], [0, 5000.0, 0]]),
                    np.array([[0, 1, 2]], np.uint32))
    scene.add(tri, name="new arrival")
    vp._refresh_camera_bounds()
    assert vp.camera.scene_bounds != first


def test_paint_refreshes_bounds_before_projecting():
    import inspect

    from serpentine3d.ui.viewport import Viewport
    src = inspect.getsource(Viewport.paintGL)
    assert src.index("_refresh_camera_bounds") < src.index("proj_matrix")
