"""Orthographic (parallel) named views — camera logic, TDD.

Written before the camera changes. The GL rendering and the actual mouse
feel are verified in the app; here we pin the projection math and the
pan/orbit decision.
"""

import numpy as np
import pytest

from serpentine3d.ui.camera import Camera, drag_pans


def test_named_ortho_views_are_parallel():
    cam = Camera()
    for name in ("top", "front", "right", "back", "left", "bottom"):
        cam.set_standard_view(name)
        assert cam.projection == "parallel", name
    cam.set_standard_view("perspective")
    assert cam.projection == "perspective"


def test_proj_matrix_is_orthographic_in_parallel():
    cam = Camera()
    cam.set_standard_view("top")
    m = cam.proj_matrix(800, 600)
    # parallel projection: w stays 1 (bottom row [0,0,0,1]) — no divide
    assert np.allclose(m[3], [0, 0, 0, 1])


def test_proj_matrix_still_perspective_otherwise():
    cam = Camera()
    cam.set_standard_view("perspective")
    m = cam.proj_matrix(800, 600)
    assert m[3, 2] == pytest.approx(-1.0)      # perspective divide by -eye_z


def test_ortho_rays_are_parallel():
    cam = Camera()
    cam.set_standard_view("top")
    cam.target[:] = (0, 0, 0)
    cam.distance = 50
    o1, d1 = cam.ray_through(120, 90, 800, 600)
    o2, d2 = cam.ray_through(700, 520, 800, 600)
    assert np.allclose(d1, d2, atol=1e-6)      # all rays share one direction
    assert not np.allclose(o1, o2)             # spread across the view plane
    assert d1[2] < -0.99                        # top looks straight down -Z


def test_ortho_centre_ray_sits_over_target():
    cam = Camera()
    cam.set_standard_view("top")
    cam.target[:] = (3, 4, 0)
    cam.distance = 50
    o, _ = cam.ray_through(400, 300, 800, 600)  # centre pixel
    assert o[0] == pytest.approx(3, abs=0.3)
    assert o[1] == pytest.approx(4, abs=0.3)


def test_ortho_projects_centre_to_screen_centre():
    cam = Camera()
    cam.set_standard_view("top")
    cam.target[:] = (0, 0, 0)
    cam.distance = 50
    scr = cam.project(np.array([[0.0, 0.0, 0.0]]), 800, 600)
    assert scr[0, 0] == pytest.approx(400, abs=1)
    assert scr[0, 1] == pytest.approx(300, abs=1)


def test_ortho_projection_depth_sign_marks_front_and_back():
    cam = Camera()
    cam.set_standard_view("top")               # camera above, looking down
    cam.target[:] = (0, 0, 0)
    cam.distance = 50
    front = cam.project(np.array([[0.0, 0.0, 0.0]]), 800, 600)   # below cam
    back = cam.project(np.array([[0.0, 0.0, 200.0]]), 800, 600)  # above cam
    assert front[0, 2] > 0
    assert back[0, 2] < 0


@pytest.mark.parametrize("projection,shift,pans", [
    ("parallel", False, True),      # ortho view: a plain drag pans
    ("parallel", True, False),      # ...Shift inverts to orbit
    ("perspective", False, False),  # perspective: a plain drag orbits
    ("perspective", True, True),    # ...Shift inverts to pan
])
def test_drag_pans_decides_pan_vs_orbit(projection, shift, pans):
    assert drag_pans(projection, shift) is pans
