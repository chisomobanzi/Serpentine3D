"""Snapping works with an imported mesh in the scene.

With an OBJ imported and the pointer over the pane, asking for a point raised
`AttributeError: 'MeshShape' object has no attribute 'ShapeType'`: the snap
gatherer handled pictures, text and point clouds by name and treated
everything else as an OpenCascade shape. A plain mesh is none of those.

A mesh brings no end, mid or centre points of its own; it has no edges in the
CAD sense. What it keeps is what every visible object has, the nearest point
on its drawn outline, and the other objects' snaps go on working beside it.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.snaps import SnapIndex, _static_snap_points
from serpentine3d.ui.camera import Camera


def _tablet():
    return MeshShape([[0, 0, 0], [20, 0, 0], [20, 14, 0], [0, 14, 0]],
                     [[0, 1, 2], [0, 2, 3]])


def test_a_mesh_offers_no_cad_snap_points_and_does_not_raise():
    assert _static_snap_points(_tablet()) == []


def test_a_curve_end_still_snaps_with_a_mesh_beside_it():
    scene = Scene()
    scene.add(_tablet(), name="Tablet")
    end = (30.0, 5.0, 0.0)
    scene.add(g.make_line((30.0, -5.0, 0.0), end))

    camera = Camera()
    camera.set_standard_view("top")
    camera.target[:] = (15.0, 5.0, 0.0)
    camera.distance = 80.0
    index = SnapIndex(scene)

    over_the_mesh = camera.project(np.asarray([(10.0, 7.0, 0.0)]), 1000, 700)[0]
    index.find(camera, over_the_mesh[0], over_the_mesh[1], 1000, 700)

    at_the_end = camera.project(np.asarray([end]), 1000, 700)[0]
    hit = index.find(camera, at_the_end[0], at_the_end[1], 1000, 700)
    assert hit is not None and hit[1] == "end"
    assert hit[0] == pytest.approx(end, abs=1e-6)
