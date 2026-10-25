"""A mesh out at survey coordinates is clicked, swept and measured.

Display meshes keep their coordinates as float32 offsets from the point
they sit at, so everything that reads them has to say which coordinates
it wants: the mesh's own, where the numbers are small, or the world's,
where the camera is. Getting that wrong is silent. A pick would simply
land somewhere else, a band would catch nothing, and nothing would raise
anything anywhere.

So this is the sweep that would have caught it: the same handful of
gestures on a mesh at the origin and on one 500,000 units out, with the
same answers expected of both.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


FAR = (500000.0, 6200000.0, 0.0)
HOME = (0.0, 0.0, 0.0)
SIZE = 20.0


def _looking_at(scene, centre):
    """A viewport in Top view, framed on a box at `centre`."""
    view = vp_mod.Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.set_view("top")
    view.camera.target = np.asarray(centre, float)
    view.camera.distance = SIZE * 4
    view._refresh_camera_bounds()
    return view


def _box(scene, at, name="Box"):
    x, y, z = at
    return scene.add(g.make_box((x - SIZE / 2, y - SIZE / 2, z - SIZE / 2),
                                SIZE, SIZE, SIZE), name=name)


@pytest.fixture(params=[HOME, FAR], ids=["at home", "far out"])
def placed(request):
    """A box at the origin, and the same box at survey coordinates."""
    scene = Scene()
    obj = _box(scene, request.param)
    return _looking_at(scene, request.param), obj, np.asarray(request.param)


def _centre(view):
    return view.width() / 2, view.height() / 2


# -- the mesh itself -------------------------------------------------------

def test_the_mesh_is_where_the_object_is(placed):
    view, obj, at = placed
    lo, hi = obj.mesh.bounds()

    assert np.abs((np.asarray(lo) + np.asarray(hi)) / 2 - at).max() < 1e-6
    assert np.abs(np.asarray(hi) - np.asarray(lo) - SIZE).max() < 1e-6


def test_its_coordinates_cost_four_bytes_wherever_it_is(placed):
    _view, obj, _at = placed
    assert obj.mesh.local.dtype == np.float32
    assert obj.mesh.local_edges.dtype == np.float32


# -- a click ---------------------------------------------------------------

def test_a_click_in_the_middle_hits_it(placed):
    view, obj, _at = placed
    assert view.pick_object(*_centre(view)) == obj.id


def test_a_click_past_it_hits_nothing(placed):
    view, _obj, _at = placed
    assert view.pick_object(5.0, 5.0) is None


def test_the_click_lands_on_the_face_it_looks_like(placed):
    view, obj, at = placed
    where = view.point_on(obj.id, *_centre(view))

    assert where is not None
    assert where[2] == pytest.approx(at[2] + SIZE / 2, abs=1e-3)


def test_the_same_click_lands_in_the_same_spot_wherever_the_box_is():
    """The sharper way to ask it: not where the answer should be, which
    the Top view's tenth of a degree of tilt already decides, but that
    moving the box 500,000 units does not move the answer within it."""
    answers = []
    for at in (HOME, FAR):
        scene = Scene()
        obj = _box(scene, at)
        view = _looking_at(scene, at)
        where = view.point_on(obj.id, *_centre(view))
        answers.append(np.asarray(where, float) - np.asarray(at, float))

    assert np.abs(answers[0] - answers[1]).max() < 1e-4


# -- a band over it --------------------------------------------------------

def test_a_band_around_it_catches_it(placed):
    view, obj, _at = placed
    ids = view._box_pick(10.0, 10.0, view.width() - 10.0, view.height() - 10.0,
                         crossing=False)
    assert ids == [obj.id]


def test_a_band_beside_it_catches_nothing(placed):
    view, _obj, _at = placed
    assert view._box_pick(2.0, 2.0, 20.0, 20.0, crossing=True) == []


def test_a_crossing_band_over_one_corner_catches_it(placed):
    view, obj, _at = placed
    cx, cy = _centre(view)
    ids = view._box_pick(cx - 10.0, cy - 10.0, cx + 400.0, cy + 400.0,
                         crossing=True)
    assert obj.id in ids


def test_a_dashed_linetype_keeps_the_mesh_s_own_coordinates(placed):
    """The buffers take offsets, so the dasher has to give them back:
    the world's numbers here would put a far object twice as far out as
    it is, and nothing on screen would say why."""
    view, obj, _at = placed
    mesh = obj.mesh
    if not len(mesh.local_edges):
        pytest.skip("nothing dashed to look at")

    dashed = vp_mod._dashed_edge_segments(mesh, (2.0, 1.0), 1.0)

    assert np.abs(np.asarray(dashed)).max() <= SIZE * 2


# -- and the same by its parts ---------------------------------------------

def test_sweeping_its_faces_names_the_same_ones_wherever_it_is(placed):
    view, obj, _at = placed
    caught = view._box_pick_subobjects(
        10.0, 10.0, view.width() - 10.0, view.height() - 10.0,
        crossing=False)
    kinds = {kind for _oid, kind, _i in caught}

    assert caught, "a sweep over the whole box caught none of its parts"
    assert kinds <= {"face", "edge"}
    assert all(oid == obj.id for oid, _k, _i in caught)
