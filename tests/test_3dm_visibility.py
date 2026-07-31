"""Hidden things stay hidden across a .3dm round trip (GitHub #5).

The importer read a layer's name and colour but never its Visible or Locked
flags, and never an object's own hidden state — so a drawing organised the
way working Rhino files are, with reference and construction layers switched
off, arrived with everything on show. Export dropped the same flags on the
way out.
"""

import rhino3dm as r3

from serpentine3d import fileio
from serpentine3d.core.scene import Scene


def _file_with_hidden_things(path: str):
    model = r3.File3dm()

    shown = r3.Layer()
    shown.Name = "Walls"
    shown.Color = (200, 100, 50, 255)
    model.Layers.Add(shown)

    hidden = r3.Layer()
    hidden.Name = "Reference"
    hidden.Color = (50, 100, 200, 255)
    hidden.Visible = False
    hidden.Locked = True
    model.Layers.Add(hidden)

    def sphere(x, name, layer, visible=True):
        attrs = r3.ObjectAttributes()
        attrs.Name = name
        attrs.LayerIndex = layer
        attrs.Visible = visible
        model.Objects.AddSphere(r3.Sphere(r3.Point3d(x, 0, 0), 2.0), attrs)

    sphere(0, "shown sphere", 0)
    sphere(10, "hidden sphere", 0, visible=False)
    sphere(20, "reference sphere", 1)
    assert model.Write(path, 8)


def test_import_preserves_layer_visibility_and_lock(tmp_path):
    path = str(tmp_path / "hidden.3dm")
    _file_with_hidden_things(path)
    scene = Scene()
    fileio.import_file(scene, path)

    walls = scene.layers.find_by_name("Walls")
    reference = scene.layers.find_by_name("Reference")
    assert walls is not None and walls.visible and not walls.locked
    assert reference is not None
    assert not reference.visible
    assert reference.locked


def test_import_preserves_object_hidden_state(tmp_path):
    path = str(tmp_path / "hidden.3dm")
    _file_with_hidden_things(path)
    scene = Scene()
    fileio.import_file(scene, path)

    assert scene.find_by_name("shown sphere").visible
    assert not scene.find_by_name("hidden sphere").visible
    # on a hidden layer, but not itself hidden: layer state carries that
    assert scene.find_by_name("reference sphere").visible


def test_export_writes_visibility_back(tmp_path):
    path = str(tmp_path / "hidden.3dm")
    _file_with_hidden_things(path)
    scene = Scene()
    fileio.import_file(scene, path)

    out = str(tmp_path / "out.3dm")
    fileio.export_file(scene, out)
    model = r3.File3dm.Read(out)
    layers = {model.Layers[i].Name: model.Layers[i]
              for i in range(len(model.Layers))}
    assert layers["Walls"].Visible
    assert not layers["Reference"].Visible
    assert layers["Reference"].Locked
    objects = {o.Attributes.Name: o.Attributes for o in model.Objects}
    assert objects["shown sphere"].Visible
    assert not objects["hidden sphere"].Visible
