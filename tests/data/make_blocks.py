"""Write tests/data/blocks.3dm — the fixture the block import tests read.

Run it by hand when the fixture needs to change:

    .venv/bin/python tests/data/make_blocks.py tests/data/blocks.3dm

It is not a fixture function because it cannot be one. rhino3dm 8.17's
InstanceDefinitions.Add segfaults once numpy is loaded in the same process,
and numpy is loaded by the time any test runs, so the file has to be built by
an interpreter that has never imported it and then committed. Reading blocks
back is fine; it is only writing them that falls over.

The file is meant to be awkward on purpose: a definition used twice, a
definition inside a definition, an instance scaled unevenly, a member on a
different layer from the instance, a member whose colour comes from its
parent, and a loose object so block content can be told from ordinary
content.
"""
import sys

import rhino3dm as r3


def _layer(model, name, color):
    layer = r3.Layer()
    layer.Name = name
    layer.Color = color
    return model.Layers.Add(layer)


def _attrs(name="", layer=0, color=None, source=None):
    a = r3.ObjectAttributes()
    a.Name = name
    a.LayerIndex = layer
    if color is not None:
        a.ObjectColor = color
    if source is not None:
        a.ColorSource = source
    return a


def build(path):
    model = r3.File3dm()
    blocks = _layer(model, "blocks", (200, 40, 40, 255))
    steel = _layer(model, "steel", (40, 40, 200, 255))

    # "widget": a box on the steel layer and a mast that takes its colour
    # from whatever instance it is standing in
    box = r3.Brep.CreateFromBox(r3.Box(r3.BoundingBox(
        r3.Point3d(0, 0, 0), r3.Point3d(2, 2, 2))))
    mast = r3.LineCurve(r3.Point3d(1, 1, 2), r3.Point3d(1, 1, 6))
    widget = model.InstanceDefinitions.Add(
        "widget", "a box and a mast", "", "", r3.Point3d(0, 0, 0),
        (box, mast),
        (_attrs("body", steel),
         _attrs("mast", blocks,
                source=r3.ObjectColorSource.ColorFromParent)))
    widget_id = model.InstanceDefinitions[widget].Id

    # "assembly": a widget lifted 10 up, plus a rail of its own
    inner = r3.InstanceReference(widget_id, r3.Transform.Translation(0, 0, 10))
    rail = r3.LineCurve(r3.Point3d(0, 0, 0), r3.Point3d(8, 0, 0))
    assembly = model.InstanceDefinitions.Add(
        "assembly", "a widget on a rail", "", "", r3.Point3d(0, 0, 0),
        (inner, rail), (_attrs("inner widget"), _attrs("rail", steel)))
    assembly_id = model.InstanceDefinitions[assembly].Id

    def place(idef_id, xform, name, **kw):
        model.Objects.AddInstanceObject(r3.InstanceReference(idef_id, xform),
                                        _attrs(name, blocks, **kw))

    place(widget_id, r3.Transform.Translation(10, 0, 0), "widget 1")
    # a green instance: the mast inside it should come out green too
    place(widget_id, r3.Transform.Translation(20, 0, 0), "widget 2",
          color=(30, 200, 60, 255),
          source=r3.ObjectColorSource.ColorFromObject)
    # taller than it is wide — not a similarity, so not a plain gp_Trsf
    place(widget_id, r3.Transform.Scale(r3.Plane.WorldXY(), 1.0, 1.0, 3.0),
          "squashed widget")
    place(assembly_id, r3.Transform.Translation(0, 30, 0), "assembly 1")

    model.Objects.AddCurve(
        r3.LineCurve(r3.Point3d(-5, 0, 0), r3.Point3d(-5, 0, 3)),
        _attrs("loose line", blocks))

    if not model.Write(path, 8):
        raise SystemExit(f"could not write {path}")
    print(f"wrote {path}: {len(model.Objects)} objects, "
          f"{len(model.InstanceDefinitions)} definitions")


if __name__ == "__main__":
    build(sys.argv[1])
