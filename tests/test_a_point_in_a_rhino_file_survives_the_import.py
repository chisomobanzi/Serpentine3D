"""A point object in a .3dm arrives, and a promise that cannot be kept
does not become a ghost.

Found by driving the real program on macOS while chasing the second half
of issue #10, then reproduced on Linux. A Rhino `Point` had no branch in
the importer at all, so it converted to nothing. A visible one was
therefore dropped in silence. A hidden one is worse: hidden objects are
imported as a promise to convert later, so the scene gained an object
whose geometry never appeared, and the next thing to ask for its bounds
got `TypeError: AddOptimal_s() … Invoked with: None`, over and over,
until the session was restarted. `v4_Wheel_PG.3dm` from the openNURBS
samples has exactly that: eleven hidden objects, one of them a point.

Three things had to be wrong at once, so all three are pinned here: the
point converts, a promise that comes back empty takes its object with it,
and asking for the bounds of nothing says so in words.
"""

from __future__ import annotations

import pytest

rhino3dm = pytest.importorskip("rhino3dm")

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


def _file_with_points(tmp_path, hidden=True):
    """A .3dm holding one visible point and, optionally, one hidden."""
    model = rhino3dm.File3dm()
    seen = rhino3dm.ObjectAttributes()
    seen.Visible = True
    seen.Name = "Seen"
    model.Objects.AddPoint(rhino3dm.Point3d(1, 2, 3), seen)
    if hidden:
        out_of_sight = rhino3dm.ObjectAttributes()
        out_of_sight.Visible = False
        out_of_sight.Name = "Hidden"
        model.Objects.AddPoint(rhino3dm.Point3d(4, 5, 6), out_of_sight)
    path = tmp_path / "points.3dm"
    assert model.Write(str(path), 7)
    return str(path)


def _points(scene):
    return [o for o in scene.all() if o.kind == "point"]


def test_a_visible_point_is_imported(tmp_path):
    scene = Scene()

    fileio.import_file(scene, _file_with_points(tmp_path, hidden=False))

    points = _points(scene)
    assert len(points) == 1, "a point object is a real object, not nothing"
    assert g.point_coords(points[0].shape) == pytest.approx((1, 2, 3))


def test_a_hidden_point_is_imported_too(tmp_path):
    scene = Scene()

    fileio.import_file(scene, _file_with_points(tmp_path))

    hidden = [o for o in _points(scene) if not o.visible]
    assert len(hidden) == 1
    realised = scene.realise(hidden[0].id)
    assert realised is not None and realised.shape is not None, (
        "a hidden point is converted late, but it is still converted")
    assert g.point_coords(realised.shape) == pytest.approx((4, 5, 6))


def test_reading_the_scene_afterwards_still_works(tmp_path):
    """The bug as it was actually met: everything that walks object bounds
    raised, and kept raising, once such a file had been opened."""
    from PySide6.QtWidgets import QApplication
    from serpentine3d.api import SerpApi
    from serpentine3d.app import MainWindow

    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        fileio.import_file(win.scene, _file_with_points(tmp_path))

        info = SerpApi(win).scene_info()

        assert info["object_count"] == len(win.scene.all())
        assert any(o["kind"] == "point" for o in info["objects"])
    finally:
        win.mark_saved()
        win.close()


def test_a_promise_that_comes_back_empty_takes_its_object_with_it():
    """Some geometry really does convert to nothing. That must leave no
    object behind rather than one with no shape."""
    from serpentine3d.core.deferred import DeferredShape

    scene = Scene()
    obj = scene.add(DeferredShape(lambda: [], kind="surface"), name="Empty")

    assert scene.realise(obj.id) is None
    assert scene.get(obj.id) is None, (
        "an object whose geometry never arrives is not an object")


def test_asking_for_the_bounds_of_nothing_says_so():
    """The old answer was a pybind TypeError about argument types, which
    reads like a version mismatch and sent me looking in the wrong place."""
    with pytest.raises(g.GeometryError):
        g.bbox(None)
