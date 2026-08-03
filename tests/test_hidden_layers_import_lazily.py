"""Opening a file does not convert what the file says is switched off (#5).

The reporter opens survey drawings with three layers ticked out of many.
Everything else was read, converted into OCC geometry and thrown at the
GPU before the window appeared. Nothing draws it, so all of that is work
for a picture nobody sees.

These are the two import paths, both of which have to do it: the plain one
for small files, and the process pool that anything over 8 MB takes — which
is every drawing this is actually for.
"""

import pytest

rhino3dm = pytest.importorskip("rhino3dm")

from serpentine3d.core.deferred import DeferredShape          # noqa: E402
from serpentine3d.core.scene import Scene                     # noqa: E402
from serpentine3d.fileio import import_file                   # noqa: E402
from serpentine3d.fileio import rhino                         # noqa: E402


def _file(tmp_path, name="mixed.3dm", hide_layer=True, boxes=3):
    """A file with a shown layer and a switched-off one, boxes on each."""
    model = rhino3dm.File3dm()

    shown = rhino3dm.Layer()
    shown.Name = "Shown"
    shown.Visible = True
    shown_i = model.Layers.Add(shown)

    off = rhino3dm.Layer()
    off.Name = "Reference"
    off.Visible = not hide_layer
    off_i = model.Layers.Add(off)

    for i in range(boxes):
        for layer_i in (shown_i, off_i):
            lo = rhino3dm.Point3d(i * 20.0, layer_i * 20.0, 0.0)
            hi = rhino3dm.Point3d(i * 20.0 + 10, layer_i * 20.0 + 10, 10.0)
            box = rhino3dm.Box(rhino3dm.BoundingBox(lo, hi))
            attrs = rhino3dm.ObjectAttributes()
            attrs.LayerIndex = layer_i
            attrs.Name = f"{'shown' if layer_i == shown_i else 'off'}{i}"
            model.Objects.AddBrep(rhino3dm.Brep.CreateFromBox(box), attrs)

    path = tmp_path / name
    model.Write(str(path), 8)
    return str(path)


def _deferred(scene):
    return [o for o in scene.all() if not o.shape_ready]


# -- the plain path --

def test_a_hidden_layer_arrives_unconverted(tmp_path):
    scene = Scene()
    import_file(scene, _file(tmp_path))

    assert len(_deferred(scene)) == 3, "the hidden layer should still be owed"


def test_the_shown_layer_arrives_converted(tmp_path):
    scene = Scene()
    import_file(scene, _file(tmp_path))

    ready = [o for o in scene.all() if o.shape_ready]
    assert len(ready) == 3
    assert all(o.kind == "solid" for o in ready)


def test_everything_in_the_file_is_still_in_the_scene(tmp_path):
    """Deferring is not dropping. The object count, the layers and the
    names are what they always were; only the geometry is owed."""
    scene = Scene()
    import_file(scene, _file(tmp_path))

    assert len(scene.all()) == 6
    assert {o.name for o in scene.all()} == {
        "shown0", "shown1", "shown2", "off0", "off1", "off2"}


def test_a_deferred_object_still_knows_what_it_is(tmp_path):
    scene = Scene()
    import_file(scene, _file(tmp_path))

    assert {o.kind for o in _deferred(scene)} == {"solid"}


def test_a_file_with_nothing_hidden_defers_nothing(tmp_path):
    scene = Scene()
    import_file(scene, _file(tmp_path, hide_layer=False))

    assert _deferred(scene) == []
    assert len(scene.all()) == 6


def test_the_geometry_is_right_when_it_finally_converts(tmp_path):
    """The whole thing is worthless if what comes back is not the object
    the file described. Same box, same place, whichever layer it was on."""
    scene = Scene()
    import_file(scene, _file(tmp_path))

    off = next(o for o in scene.all() if o.name == "off0")
    shown = next(o for o in scene.all() if o.name == "shown0")
    (off_lo, off_hi), (shown_lo, shown_hi) = off.bbox(), shown.bbox()

    assert off_hi[0] - off_lo[0] == pytest.approx(shown_hi[0] - shown_lo[0])
    assert off_lo[1] > shown_lo[1], "the hidden layer's boxes sit further out"


def test_switching_the_layer_on_converts_it(tmp_path):
    scene = Scene()
    import_file(scene, _file(tmp_path))
    lay = scene.layers.find_by_name("Reference")

    scene.layers.set_visible(lay.id, True)

    assert _deferred(scene) == [], "ticking the layer should have paid for it"


def test_saving_it_again_keeps_what_was_never_converted(tmp_path):
    """Deferring must not turn into losing. Export reads every object's
    shape, which converts the ones nobody had asked for yet, and what
    comes back out has to be the whole drawing."""
    from serpentine3d.fileio import export_file

    scene = Scene()
    import_file(scene, _file(tmp_path))
    out = str(tmp_path / "saved.3dm")
    export_file(scene, out)

    again = Scene()
    import_file(again, out)
    assert len(again.all()) == 6


def test_the_layer_comes_in_switched_off(tmp_path):
    """It was already so, and it is what makes the deferral invisible: you
    do not see a layer you never asked for, converted or not."""
    scene = Scene()
    import_file(scene, _file(tmp_path))

    assert not scene.layers.find_by_name("Reference").visible


def test_nothing_on_show_is_left_waiting(tmp_path):
    """A scene starts with a Default layer and the importer reuses a layer
    it already has by name, visibility and all. So a file whose own Default
    is switched off puts its objects on a layer that is switched on, and
    they would be deferred and then drawn on the very next frame. The
    conversion has to happen while the file is open, where the workers can
    share it, not one at a time inside a zoom extents."""
    model = rhino3dm.File3dm()
    off = rhino3dm.Layer()
    off.Name = "Default"
    off.Visible = False
    off_i = model.Layers.Add(off)
    for i in range(3):
        lo = rhino3dm.Point3d(i * 20.0, 0.0, 0.0)
        hi = rhino3dm.Point3d(i * 20.0 + 10, 10.0, 10.0)
        attrs = rhino3dm.ObjectAttributes()
        attrs.LayerIndex = off_i
        attrs.Name = f"box{i}"
        model.Objects.AddBrep(
            rhino3dm.Brep.CreateFromBox(
                rhino3dm.Box(rhino3dm.BoundingBox(lo, hi))), attrs)
    path = str(tmp_path / "default_off.3dm")
    model.Write(path, 8)

    scene = Scene()
    import_file(scene, path)

    assert [o.name for o in scene.visible_objects() if not o.shape_ready] == []


def _default_off(tmp_path, name="default_off.3dm"):
    """A file whose own Default layer is switched off, holding three boxes."""
    model = rhino3dm.File3dm()
    off = rhino3dm.Layer()
    off.Name = "Default"
    off.Visible = False
    off_i = model.Layers.Add(off)
    for i in range(3):
        lo = rhino3dm.Point3d(i * 20.0, 0.0, 0.0)
        hi = rhino3dm.Point3d(i * 20.0 + 10, 10.0, 10.0)
        attrs = rhino3dm.ObjectAttributes()
        attrs.LayerIndex = off_i
        attrs.Name = f"box{i}"
        model.Objects.AddBrep(
            rhino3dm.Brep.CreateFromBox(
                rhino3dm.Box(rhino3dm.BoundingBox(lo, hi))), attrs)
    path = str(tmp_path / name)
    model.Write(path, 8)
    return path


def test_importing_does_not_hide_work_already_on_the_layer(tmp_path):
    """The rule above is only safe while the layer is empty. Import a file
    whose Default is switched off into a drawing that has something on its
    own Default, and that something has to stay on show."""
    from serpentine3d.core import geometry as g

    scene = Scene()
    mine = scene.add(g.make_box((0, 0, 0), 5, 5, 5), name="Mine")

    import_file(scene, _default_off(tmp_path, "into.3dm"))

    assert scene.layers.find_by_name("Default").visible
    assert mine in scene.visible_objects()


# -- and the pool, which is what a real drawing goes through --

def test_the_parallel_path_defers_too(tmp_path):
    """Forced rather than waited for: the pool only takes files over 8 MB
    and a fixture that size would make this test cost minutes."""
    path = _file(tmp_path, name="parallel.3dm")
    items = rhino.import_3dm_parallel(path)

    deferred = [s for _, s, _ in items if isinstance(s, DeferredShape)]
    assert len(deferred) == 3


def test_the_parallel_path_converts_what_is_shown(tmp_path):
    path = _file(tmp_path, name="parallel.3dm")
    items = rhino.import_3dm_parallel(path)

    real = [s for _, s, _ in items if not isinstance(s, DeferredShape)]
    assert len(real) == 3


def test_what_the_pool_deferred_converts_to_the_same_thing(tmp_path):
    """The pool cannot send geometry it never converted, so its placeholder
    reopens the file. It has to land on the same object it skipped."""
    path = _file(tmp_path, name="parallel.3dm")
    items = rhino.import_3dm_parallel(path)

    by_name = {name: shape for name, shape, _ in items}
    shapes = by_name["off0"].shapes()
    assert len(shapes) == 1

    from serpentine3d.core import geometry as g
    assert g.shape_kind(shapes[0]) == "solid"


def test_both_paths_produce_the_same_drawing(tmp_path):
    """Which path a file takes is a size threshold, not a decision anyone
    made. The scene must not be able to tell."""
    path = _file(tmp_path, name="both.3dm")

    serial = rhino.import_3dm(path)
    parallel = rhino.import_3dm_parallel(path)

    def summary(items):
        return sorted((name, isinstance(shape, DeferredShape),
                       meta.get("layer"))
                      for name, shape, meta in items)

    assert summary(serial) == summary(parallel)
