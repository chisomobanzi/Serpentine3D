"""The isometric named view.

Asked for by a tester. Isometric is not "some corner view": it is the one
angle where the three world axes come out the same length on screen and
120 degrees apart, so a cube reads as a cube and you can measure along all
three directions off the same drawing. That property is what these tests
pin, rather than the pair of angles that happens to produce it.
"""

import math

import numpy as np
import pytest

from serpentine3d.ui.camera import Camera


def _axes_on_screen(cam):
    """The three world axes as 2D screen vectors from the origin."""
    pts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    scr = cam.project(pts, 800, 600)[:, :2]
    return [scr[i] - scr[0] for i in (1, 2, 3)]


@pytest.fixture
def iso():
    cam = Camera()
    cam.set_standard_view("isometric")
    cam.target[:] = (0, 0, 0)
    cam.distance = 50
    return cam


def test_isometric_is_a_named_view():
    cam = Camera()
    cam.set_standard_view("isometric")       # must not raise


def test_the_three_axes_come_out_the_same_length(iso):
    x, y, z = (float(np.linalg.norm(v)) for v in _axes_on_screen(iso))
    assert y == pytest.approx(x, rel=1e-3)
    assert z == pytest.approx(x, rel=1e-3)


def test_the_cube_corner_nearest_you_splits_the_screen_evenly(iso):
    """The three edges meeting at the near corner sit 120 degrees apart.

    Which of the six signed axes those are depends on the octant you are
    standing in, so they are read off the view rather than assumed: whichever
    corner of a cube comes out nearest, its edges fan out evenly. That even
    fan is what people mean by an isometric drawing.
    """
    cube = np.array([[sx, sy, sz] for sx in (-1.0, 1.0)
                     for sy in (-1.0, 1.0) for sz in (-1.0, 1.0)])
    scr = iso.project(cube, 800, 600)
    near = cube[int(np.argmin(scr[:, 2]))]        # smaller depth is nearer
    # the three edges leaving that corner run back across the cube
    ends = np.array([near] + [near - near * axis for axis in np.eye(3)])
    flat = iso.project(ends, 800, 600)[:, :2]
    angles = sorted(math.degrees(math.atan2(v[1], v[0])) % 360
                    for v in (flat[1] - flat[0], flat[2] - flat[0],
                              flat[3] - flat[0]))
    gaps = [(b - a) for a, b in zip(angles, angles[1:] + [angles[0] + 360])]
    for gap in gaps:
        assert gap == pytest.approx(120.0, abs=0.5)


def test_isometric_is_parallel_not_perspective(iso):
    """Foreshortening would undo the equal axes the moment anything moves
    off the origin, which is the whole point of the view.
    """
    assert iso.projection == "parallel"


def test_z_still_points_up_the_screen(iso):
    """Standing on a corner is one thing; standing on your head is another."""
    _, _, z = _axes_on_screen(iso)
    assert z[1] < 0                      # screen y grows downwards


def test_isometric_looks_down_at_the_model(iso):
    o, d = iso.ray_through(400, 300, 800, 600)
    assert d[2] < 0                      # from above, looking down
    assert o[2] > 0
